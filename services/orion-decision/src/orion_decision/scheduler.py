# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Scheduler for Orion tasks"""
import re
from logging import getLogger
from pathlib import Path
from string import Template

from taskcluster.exceptions import TaskclusterFailure
from taskcluster.utils import slugId, stringDate
from yaml import safe_load as yaml_load

from . import (
    ARTIFACTS_EXPIRE,
    DEADLINE,
    MAX_RUN_TIME,
    OWNER_EMAIL,
    PROVISIONER_ID,
    SCHEDULER_ID,
    SOURCE_URL,
    WORKER_TYPE,
    Taskcluster,
)
from .git import GithubEvent
from .orion import Services

LOG = getLogger(__name__)
TEMPLATES = (Path(__file__).parent / "task_templates").resolve()
BUILD_TASK = Template((TEMPLATES / "build.yaml").read_text())
PUSH_TASK = Template((TEMPLATES / "push.yaml").read_text())
TEST_TASK = Template((TEMPLATES / "test.yaml").read_text())


class Scheduler:
    """Decision logic for scheduling Orion build/push tasks in Taskcluster.

    Attributes:
        github_event (GithubEvent): The event that triggered this decision.
        now (datetime): The time to calculate task times from.
        task_group (str): The taskGroupID to add created tasks to.
        docker_secret (str): The Taskcluster secret name holding Docker Hub credentials.
        push_branch (str): The branch name that should trigger a push to Docker Hub.
        services (Services): The services
        dry_run (bool): Perform everything *except* actually queuing tasks in TC.
    """

    def __init__(
        self, github_event, now, task_group, docker_secret, push_branch, dry_run=False
    ):
        """Initialize a Scheduler instance.

        Arguments:
            github_event (GithubEvent): The event that triggered this decision.
            now (datetime): The time to calculate task times from.
            task_group (str): The taskGroupID to add created tasks to.
            docker_secret (str): The Taskcluster secret name holding Docker Hub creds.
            push_branch (str): The branch name that should trigger a push to Docker Hub.
            dry_run (bool): Don't actually queue tasks in Taskcluster.
        """
        self.github_event = github_event
        self.now = now
        self.task_group = task_group
        self.docker_secret = docker_secret
        self.push_branch = push_branch
        self.dry_run = dry_run
        self.services = Services(self.github_event.repo)

    def mark_services_for_rebuild(self):
        """Check for services that need to be rebuilt.
        These will have their `dirty` attribute set, which is used to create tasks.

        Returns:
            None
        """
        forced = set()
        for match in re.finditer(
            r"/force-rebuild(=[A-Za-z0-9_.,-]+)?", self.github_event.commit_message
        ):
            if "=" in match.group(0):
                for svc in match.group(1)[1:].split(","):
                    assert (
                        svc in self.services
                    ), f"/force-rebuild of unknown service {svc}"
                    self.services[svc].dirty = True
                    forced.add(svc)
            else:
                LOG.info("/force-rebuild detected, all services will be marked dirty")
                for service in self.services.values():
                    service.dirty = True
                return  # short-cut, no point in continuing
        if forced:
            LOG.info(
                "/force-rebuild detected for service: %s", ", ".join(sorted(forced))
            )
        self.services.mark_changed_dirty(self.github_event.list_changed_paths())

    def create_tasks(self):
        """Create test/build/push tasks in Taskcluster.

        Returns:
            None
        """
        if self.github_event.event_type == "release":
            LOG.warning("Detected release event. Nothing to do!")
            return
        should_push = (
            self.github_event.event_type == "push"
            and self.github_event.branch == self.push_branch
        )
        queue = Taskcluster.get_service("queue")
        service_build_tasks = {service: slugId() for service in self.services}
        test_tasks_created = set()
        build_tasks_created = set()
        push_tasks_created = set()
        if not should_push:
            LOG.info(
                "Not pushing to Docker Hub (event is %s, branch is %s, only push %s)",
                self.github_event.event_type,
                self.github_event.branch,
                self.push_branch,
            )
        if self.dry_run:
            created_msg = create_msg = "Would create"
        else:
            create_msg = "Creating"
            created_msg = "Created"
        services_to_create = list(sorted(self.services.values(), key=lambda x: x.name))
        while services_to_create:
            service = services_to_create.pop(0)
            if self.github_event.pull_request is not None:
                build_index = (
                    f"index.project.fuzzing.orion.{service.name}"
                    f".pull_request.{self.github_event.pull_request}"
                )
            else:
                build_index = (
                    f"index.project.fuzzing.orion.{service.name}"
                    f".{self.github_event.branch}"
                )
            if not service.dirty:
                LOG.info("service %s doesn't need to be rebuilt", service.name)
                continue
            dirty_dep_tasks = [
                service_build_tasks[dep]
                for dep in service.service_deps
                if self.services[dep].dirty
            ]
            dirty_test_dep_tasks = [
                service_build_tasks[test.image]
                for test in service.tests
                if test.image in service_build_tasks and self.services[test.image].dirty
            ]

            if (set(dirty_dep_tasks) | set(dirty_test_dep_tasks)) - build_tasks_created:
                LOG.debug(
                    "Can't create %s before dependencies: %s",
                    service.name,
                    list(
                        (set(dirty_dep_tasks) | set(dirty_test_dep_tasks))
                        - build_tasks_created
                    ),
                )
                services_to_create.append(service)
                continue

            test_tasks = []
            for test in service.tests:
                image = test.image
                deps = []
                if image in service_build_tasks:
                    if self.services[image].dirty:
                        deps.append(service_build_tasks[image])
                        image = {
                            "type": "task-image",
                            "taskId": service_build_tasks[image],
                        }
                    else:
                        image = {
                            "type": "indexed-image",
                            "namespace": (
                                f"project.fuzzing.orion.{image}.{self.push_branch}"
                            ),
                        }
                    image["path"] = f"public/{test.image}.tar.zst"
                test_task = yaml_load(
                    TEST_TASK.substitute(
                        deadline=stringDate(self.now + DEADLINE),
                        max_run_time=int(MAX_RUN_TIME.total_seconds()),
                        now=stringDate(self.now),
                        owner_email=OWNER_EMAIL,
                        provisioner=PROVISIONER_ID,
                        scheduler=SCHEDULER_ID,
                        service_name=service.name,
                        source_url=SOURCE_URL,
                        task_group=self.task_group,
                        test_name=test.name,
                        worker=WORKER_TYPE,
                    )
                )
                test_task["payload"]["image"] = image
                test_task["dependencies"].extend(deps)
                service_path = str(service.root.relative_to(self.services.root))
                test.update_task(
                    test_task,
                    self.github_event.clone_url,
                    self.github_event.fetch_ref,
                    self.github_event.commit,
                    service_path,
                )
                task_id = slugId()
                LOG.info(
                    "%s task %s: %s", create_msg, task_id, test_task["metadata"]["name"]
                )
                if not self.dry_run:
                    try:
                        queue.createTask(task_id, test_task)
                    except TaskclusterFailure as exc:  # pragma: no cover
                        LOG.error("Error creating test task: %s", exc)
                        raise
                test_tasks_created.add(task_id)
                test_tasks.append(task_id)
            build_task = yaml_load(
                BUILD_TASK.substitute(
                    clone_url=self.github_event.clone_url,
                    commit=self.github_event.commit,
                    deadline=stringDate(self.now + DEADLINE),
                    dockerfile=str(service.dockerfile.relative_to(service.context)),
                    expires=stringDate(self.now + ARTIFACTS_EXPIRE),
                    load_deps="1" if dirty_dep_tasks else "0",
                    max_run_time=int(MAX_RUN_TIME.total_seconds()),
                    now=stringDate(self.now),
                    owner_email=OWNER_EMAIL,
                    provisioner=PROVISIONER_ID,
                    route=build_index,
                    scheduler=SCHEDULER_ID,
                    service_name=service.name,
                    source_url=SOURCE_URL,
                    task_group=self.task_group,
                    worker=WORKER_TYPE,
                )
            )
            build_task["dependencies"].extend(dirty_dep_tasks + test_tasks)
            task_id = service_build_tasks[service.name]
            LOG.info(
                "%s task %s: %s", create_msg, task_id, build_task["metadata"]["name"]
            )
            if not self.dry_run:
                try:
                    queue.createTask(task_id, build_task)
                except TaskclusterFailure as exc:  # pragma: no cover
                    LOG.error("Error creating build task: %s", exc)
                    raise
            build_tasks_created.add(task_id)
            if not should_push:
                continue
            push_task = yaml_load(
                PUSH_TASK.substitute(
                    clone_url=self.github_event.clone_url,
                    commit=self.github_event.commit,
                    deadline=stringDate(self.now + DEADLINE),
                    docker_secret=self.docker_secret,
                    max_run_time=int(MAX_RUN_TIME.total_seconds()),
                    now=stringDate(self.now),
                    owner_email=OWNER_EMAIL,
                    provisioner=PROVISIONER_ID,
                    scheduler=SCHEDULER_ID,
                    service_name=service.name,
                    source_url=SOURCE_URL,
                    task_group=self.task_group,
                    worker=WORKER_TYPE,
                )
            )
            push_task["dependencies"].append(service_build_tasks[service.name])
            task_id = slugId()
            LOG.info(
                "%s task %s: %s", create_msg, task_id, push_task["metadata"]["name"]
            )
            if not self.dry_run:
                try:
                    queue.createTask(task_id, push_task)
                except TaskclusterFailure as exc:  # pragma: no cover
                    LOG.error("Error creating build task: %s", exc)
                    raise
            push_tasks_created.add(task_id)
        LOG.info(
            "%s %d test tasks, %d build tasks and %d push tasks",
            created_msg,
            len(test_tasks_created),
            len(build_tasks_created),
            len(push_tasks_created),
        )

    @classmethod
    def main(cls, args):
        """Decision procedure.

        Arguments:
            args (argparse.Namespace): Arguments as returned by `parse_args()`

        Returns:
            int: Shell return code.
        """
        # get the github event & repo
        evt = GithubEvent.from_taskcluster(args.github_action, args.github_event)
        try:

            # create the scheduler
            sched = cls(
                evt,
                args.now,
                args.task_group,
                args.docker_hub_secret,
                args.push_branch,
                args.dry_run,
            )

            sched.mark_services_for_rebuild()

            # schedule tasks
            sched.create_tasks()
        finally:
            evt.cleanup()

        return 0
