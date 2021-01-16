# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Scheduler for Orion tasks"""
from logging import getLogger

from taskcluster.exceptions import TaskclusterFailure
from taskcluster.utils import slugId, stringDate

from . import ARTIFACTS_EXPIRE
from . import DEADLINE
from . import MAX_RUN_TIME
from . import OWNER_EMAIL
from . import PROVISIONER_ID
from . import SCHEDULER_ID
from . import SOURCE_URL
from . import Taskcluster
from . import WORKER_TYPE
from .git import GithubEvent
from .orion import Services


LOG = getLogger(__name__)


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
        self.services = Services(self.github_event.repo.path)

    def mark_services_for_rebuild(self):
        """Check for services that need to be rebuilt.
        These will have their `dirty` attribute set, which is used to create tasks.

        Returns:
            None
        """
        if "/force-rebuild" in self.github_event.commit_message:
            LOG.info("/force-rebuild detected, all services will be marked dirty")
            for service in self.services.values():
                service.dirty = True
        else:
            self.services.mark_changed_dirty(self.github_event.list_changed_paths())

    def create_tasks(self):
        """Create build/push tasks in Taskcluster.

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
        services_to_create = list(self.services.values())
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
            if set(dirty_dep_tasks) - build_tasks_created:
                LOG.debug(
                    "Can't create %s before dependencies: %s",
                    service.name,
                    list(set(dirty_dep_tasks) - build_tasks_created),
                )
                services_to_create.append(service)
                continue
            build_task = {
                "taskGroupId": self.task_group,
                "dependencies": dirty_dep_tasks,
                "created": stringDate(self.now),
                "deadline": stringDate(self.now + DEADLINE),
                "provisionerId": PROVISIONER_ID,
                "schedulerId": SCHEDULER_ID,
                "workerType": WORKER_TYPE,
                "payload": {
                    "artifacts": {
                        f"public/{service.name}.tar.zst": {
                            "expires": stringDate(self.now + ARTIFACTS_EXPIRE),
                            "path": "/image.tar.zst",
                            "type": "file",
                        },
                    },
                    "command": ["build"],
                    "env": {
                        "ARCHIVE_PATH": "/image.tar",
                        "BUILD_TOOL": "img",
                        "DOCKERFILE": str(
                            service.dockerfile.relative_to(service.context)
                        ),
                        "GIT_REPOSITORY": self.github_event.clone_url,
                        "GIT_REVISION": self.github_event.commit,
                        "IMAGE_NAME": f"mozillasecurity/{service.name}",
                        "LOAD_DEPS": "1" if dirty_dep_tasks else "0",
                    },
                    "capabilities": {"privileged": True},
                    "image": "mozillasecurity/orion-builder:latest",
                    "maxRunTime": MAX_RUN_TIME.total_seconds(),
                },
                "routes": [
                    (
                        f"index.project.fuzzing.orion.{service.name}"
                        f".rev.{self.github_event.commit}"
                    ),
                    build_index,
                ],
                "scopes": [
                    "docker-worker:capability:privileged",
                    "queue:route:index.project.fuzzing.orion.*",
                    f"queue:scheduler-id:{SCHEDULER_ID}",
                ],
                "metadata": {
                    "description": f"Build the docker image for {service.name} tasks",
                    "name": f"Orion {service.name} docker build",
                    "owner": OWNER_EMAIL,
                    "source": SOURCE_URL,
                },
            }
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
            push_task = {
                "taskGroupId": self.task_group,
                "dependencies": [service_build_tasks[service.name]],
                "created": stringDate(self.now),
                "deadline": stringDate(self.now + DEADLINE),
                "provisionerId": PROVISIONER_ID,
                "schedulerId": SCHEDULER_ID,
                "workerType": WORKER_TYPE,
                "payload": {
                    "command": ["push"],
                    "env": {
                        "BUILD_TOOL": "img",
                        "GIT_REPOSITORY": self.github_event.clone_url,
                        "GIT_REVISION": self.github_event.commit,
                        "IMAGE_NAME": f"mozillasecurity/{service.name}",
                        "TASKCLUSTER_SECRET": self.docker_secret,
                    },
                    "features": {"taskclusterProxy": True},
                    "image": "mozillasecurity/orion-builder:latest",
                    "maxRunTime": MAX_RUN_TIME.total_seconds(),
                },
                "scopes": [
                    f"queue:scheduler-id:{SCHEDULER_ID}",
                    f"secrets:get:{self.docker_secret}",
                ],
                "metadata": {
                    "description": (
                        f"Publish the docker image for {service.name} tasks"
                    ),
                    "name": f"Orion {service.name} docker push",
                    "owner": OWNER_EMAIL,
                    "source": SOURCE_URL,
                },
            }
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
            "%s %d build tasks and %d push tasks",
            created_msg,
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
