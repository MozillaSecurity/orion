# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Scheduler for Orion tasks"""

import argparse
import re
from datetime import datetime
from logging import getLogger
from pathlib import Path
from string import Template
from typing import Dict, List, Optional, Set, Union

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
    WORKER_TYPE_BREW,
    WORKER_TYPE_MSYS,
    Taskcluster,
)
from .git import GithubEvent
from .orion import (
    Recipe,
    Service,
    ServiceHomebrew,
    ServiceMsys,
    Services,
    ToxServiceTest,
)

LOG = getLogger(__name__)
TEMPLATES = (Path(__file__).parent / "task_templates").resolve()
BUILD_TASK = Template((TEMPLATES / "build.yaml").read_text())
MSYS_TASK = Template((TEMPLATES / "build_msys.yaml").read_text())
MSYS_EXE_TASK = Template((TEMPLATES / "build_msys_exe.yaml").read_text())
HOMEBREW_TASK = Template((TEMPLATES / "build_homebrew.yaml").read_text())
PUSH_TASK = Template((TEMPLATES / "push.yaml").read_text())
TEST_TASK = Template((TEMPLATES / "test.yaml").read_text())
RECIPE_TEST_TASK = Template((TEMPLATES / "recipe_test.yaml").read_text())


class Scheduler:
    """Decision logic for scheduling Orion build/push tasks in Taskcluster.

    Attributes:
        github_event: The event that triggered this decision.
        now: The time to calculate task times from.
        task_group: The taskGroupID to add created tasks to.
        docker_secret: The Taskcluster secret name holding Docker Hub credentials.
        push_branch: The branch name that should trigger a push to Docker Hub.
        services (Services): The services
        dry_run: Perform everything *except* actually queuing tasks in TC.
    """

    def __init__(
        self,
        github_event: GithubEvent,
        now: Optional[datetime],
        task_group: str,
        docker_secret: str,
        push_branch: str,
        dry_run: bool = False,
    ) -> None:
        """Initialize a Scheduler instance.

        Arguments:
            github_event: The event that triggered this decision.
            now: The time to calculate task times from.
            task_group: The taskGroupID to add created tasks to.
            docker_secret: The Taskcluster secret name holding Docker Hub creds.
            push_branch: The branch name that should trigger a push to Docker Hub.
            dry_run: Don't actually queue tasks in Taskcluster.
        """
        self.github_event = github_event
        self.now = now
        self.task_group = task_group
        self.docker_secret = docker_secret
        self.push_branch = push_branch
        self.dry_run = dry_run
        assert self.github_event.repo is not None
        self.services = Services(self.github_event.repo)

    def _build_index(self, svc_name: str) -> str:
        if self.github_event.pull_request is not None:
            build_index = (
                f"index.project.fuzzing.orion.{svc_name}"
                f".pull_request.{self.github_event.pull_request}"
            )
        else:
            build_index = (
                f"index.project.fuzzing.orion.{svc_name}.{self.github_event.branch}"
            )
        return build_index

    def _clone_url(self) -> str:
        return self.github_event.http_url

    def _commit(self) -> str:
        assert self.github_event.commit is not None
        return self.github_event.commit

    def _fetch_ref(self) -> str:
        assert self.github_event.fetch_ref is not None
        return self.github_event.fetch_ref

    def _push_branch(self) -> str:
        return self.push_branch

    def _should_push(self) -> bool:
        should_push = (
            self.github_event.event_type == "push"
            and self.github_event.branch == self._push_branch()
        )
        if not should_push:
            LOG.info(
                "Not pushing to Docker Hub (event is %s, branch is %s, only push %s)",
                self.github_event.event_type,
                self.github_event.branch,
                self.push_branch,
            )
        return should_push

    def _skip_tasks(self) -> bool:
        if self.github_event.event_type == "release":
            LOG.warning("Detected release event. Nothing to do!")
            return True
        return False

    def mark_services_for_rebuild(self) -> None:
        """Check for services that need to be rebuilt.
        These will have their `dirty` attribute set, which is used to create tasks.
        """
        forced = set()
        assert self.github_event.commit_message is not None
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
                return None  # short-cut, no point in continuing
        if forced:
            LOG.info(
                "/force-rebuild detected for service: %s", ", ".join(sorted(forced))
            )
        self.services.mark_changed_dirty(self.github_event.list_changed_paths())

    def _create_build_task(
        self, service, dirty_dep_tasks, test_tasks, service_build_tasks
    ):
        build_index = self._build_index(service.name)
        assert self.now is not None
        if isinstance(service, ServiceMsys):
            if service.base.endswith(".exe"):
                if not service.base.endswith(".sfx.exe"):
                    LOG.warning("'base' ends with .exe, but not .sfx.exe", service.base)
                task_template = MSYS_EXE_TASK
            else:
                task_template = MSYS_TASK
            build_task = yaml_load(
                task_template.substitute(
                    clone_url=self._clone_url(),
                    commit=self._commit(),
                    deadline=stringDate(self.now + DEADLINE),
                    expires=stringDate(self.now + ARTIFACTS_EXPIRE),
                    max_run_time=int(MAX_RUN_TIME.total_seconds()),
                    msys_base_url=service.base,
                    now=stringDate(self.now),
                    owner_email=OWNER_EMAIL,
                    provisioner=PROVISIONER_ID,
                    route=build_index,
                    scheduler=SCHEDULER_ID,
                    service_name=service.name,
                    setup_sh_path=str(
                        (service.root / "setup.sh").relative_to(service.context)
                    ),
                    source_url=SOURCE_URL,
                    task_group=self.task_group,
                    worker=WORKER_TYPE_MSYS,
                )
            )
        elif isinstance(service, ServiceHomebrew):
            build_task = yaml_load(
                HOMEBREW_TASK.substitute(
                    clone_url=self._clone_url(),
                    commit=self._commit(),
                    deadline=stringDate(self.now + DEADLINE),
                    expires=stringDate(self.now + ARTIFACTS_EXPIRE),
                    max_run_time=int(MAX_RUN_TIME.total_seconds()),
                    homebrew_base_url=service.base,
                    now=stringDate(self.now),
                    owner_email=OWNER_EMAIL,
                    provisioner=PROVISIONER_ID,
                    route=build_index,
                    scheduler=SCHEDULER_ID,
                    service_name=service.name,
                    setup_sh_path=str(
                        (service.root / "setup.sh").relative_to(service.context)
                    ),
                    source_url=SOURCE_URL,
                    task_group=self.task_group,
                    worker=WORKER_TYPE_BREW,
                )
            )
        else:
            build_task = yaml_load(
                BUILD_TASK.substitute(
                    clone_url=self._clone_url(),
                    commit=self._commit(),
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
            "%s task %s: %s", self._create_str, task_id, build_task["metadata"]["name"]
        )
        if not self.dry_run:
            try:
                Taskcluster.get_service("queue").createTask(task_id, build_task)
            except TaskclusterFailure as exc:  # pragma: no cover
                LOG.error("Error creating build task: %s", exc)
                raise
        return task_id

    def _create_push_task(self, service, service_build_tasks):
        assert self.now is not None
        push_task = yaml_load(
            PUSH_TASK.substitute(
                clone_url=self._clone_url(),
                commit=self._commit(),
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
            "%s task %s: %s", self._create_str, task_id, push_task["metadata"]["name"]
        )
        if not self.dry_run:
            try:
                Taskcluster.get_service("queue").createTask(task_id, push_task)
            except TaskclusterFailure as exc:  # pragma: no cover
                LOG.error("Error creating push task: %s", exc)
                raise
        return task_id

    def _create_svc_test_task(
        self,
        service: Service,
        test: ToxServiceTest,
        service_build_tasks: Dict[str, str],
    ):
        image: Union[str, Dict[str, str]] = test.image
        deps = []
        if image in service_build_tasks:
            if self.services[image].dirty:
                assert isinstance(image, str)
                deps.append(service_build_tasks[image])
                image = {
                    "type": "task-image",
                    "taskId": service_build_tasks[image],
                }
            else:
                image = {
                    "type": "indexed-image",
                    "namespace": f"project.fuzzing.orion.{image}.{self._push_branch()}",
                }
            image["path"] = f"public/{test.image}.tar.zst"
        assert self.now is not None
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
        assert self.services.root is not None
        service_path = str(service.root.relative_to(self.services.root))
        test.update_task(
            test_task,
            self._clone_url(),
            self._fetch_ref(),
            self._commit(),
            service_path,
        )
        task_id = slugId()
        LOG.info(
            "%s task %s: %s", self._create_str, task_id, test_task["metadata"]["name"]
        )
        if not self.dry_run:
            try:
                Taskcluster.get_service("queue").createTask(task_id, test_task)
            except TaskclusterFailure as exc:  # pragma: no cover
                LOG.error("Error creating test task: %s", exc)
                raise
        return task_id

    def _create_recipe_test_task(
        self, recipe: Recipe, dep_tasks: List[str], recipe_test_tasks: Dict[str, str]
    ) -> str:
        assert self.services.root is not None
        service_path = self.services.root / "services" / "test-recipes"
        dockerfile = service_path / f"Dockerfile-{recipe.file.stem}"
        if not dockerfile.is_file():
            dockerfile = service_path / "Dockerfile"
        assert self.now is not None
        test_task = yaml_load(
            RECIPE_TEST_TASK.substitute(
                clone_url=self._clone_url(),
                commit=self._commit(),
                deadline=stringDate(self.now + DEADLINE),
                dockerfile=str(dockerfile.relative_to(self.services.root)),
                max_run_time=int(MAX_RUN_TIME.total_seconds()),
                now=stringDate(self.now),
                owner_email=OWNER_EMAIL,
                provisioner=PROVISIONER_ID,
                recipe_name=recipe.name,
                scheduler=SCHEDULER_ID,
                source_url=SOURCE_URL,
                task_group=self.task_group,
                worker=WORKER_TYPE,
            )
        )
        test_task["dependencies"].extend(dep_tasks)
        task_id = recipe_test_tasks[recipe.name]
        LOG.info(
            "%s task %s: %s", self._create_str, task_id, test_task["metadata"]["name"]
        )
        if not self.dry_run:
            try:
                Taskcluster.get_service("queue").createTask(task_id, test_task)
            except TaskclusterFailure as exc:  # pragma: no cover
                LOG.error("Error creating recipe test task: %s", exc)
                raise
        return task_id

    @property
    def _create_str(self) -> str:
        if self.dry_run:
            return "Would create"
        return "Creating"

    @property
    def _created_str(self) -> str:
        if self.dry_run:
            return "Would create"
        return "Created"

    def create_tasks(self) -> None:
        """Create test/build/push tasks in Taskcluster."""
        if self._skip_tasks():
            return None
        should_push = self._should_push()
        service_build_tasks = {service: slugId() for service in self.services}
        recipe_test_tasks = {recipe: slugId() for recipe in self.services.recipes}
        test_tasks_created: Set[str] = set()
        build_tasks_created: Set[str] = set()
        push_tasks_created: Set[str] = set()
        to_create = sorted(
            self.services.recipes.values(), key=lambda x: x.name
        ) + sorted(self.services.values(), key=lambda x: x.name)
        while to_create:
            obj = to_create.pop(0)
            is_svc = isinstance(obj, Service)
            is_msys = isinstance(obj, ServiceMsys)
            is_brew = isinstance(obj, ServiceHomebrew)

            if not obj.dirty:
                if is_svc:
                    LOG.info("Service %s doesn't need to be rebuilt", obj.name)
                continue
            dirty_dep_tasks = [
                service_build_tasks[dep]
                for dep in obj.service_deps
                if self.services[dep].dirty
            ]
            if is_svc:
                assert isinstance(obj, Service)
                dirty_test_dep_tasks = []
                for test in obj.tests:
                    assert isinstance(test, ToxServiceTest)
                    if (
                        test.image in service_build_tasks
                        and self.services[test.image].dirty
                    ):
                        dirty_test_dep_tasks.append(service_build_tasks[test.image])
            else:
                dirty_test_dep_tasks = []
            dirty_recipe_test_tasks = [
                recipe_test_tasks[recipe]
                for recipe in obj.recipe_deps
                if self.services.recipes[recipe].dirty
            ]

            pending_deps = (
                set(dirty_dep_tasks) | set(dirty_test_dep_tasks)
            ) - build_tasks_created
            pending_deps |= set(dirty_recipe_test_tasks) - test_tasks_created
            if pending_deps:
                if is_svc:
                    task_id = service_build_tasks[obj.name]
                else:
                    task_id = recipe_test_tasks[obj.name]

                LOG.debug(
                    "Can't create %s %s task %s before dependencies: %s",
                    type(obj).__name__,
                    obj.name,
                    task_id,
                    ", ".join(pending_deps),
                )
                to_create.append(obj)
                continue

            if is_svc:
                test_tasks = []
                assert isinstance(obj, Service)
                for test in obj.tests:
                    assert isinstance(test, ToxServiceTest)
                    task_id = self._create_svc_test_task(obj, test, service_build_tasks)
                    test_tasks_created.add(task_id)
                    test_tasks.append(task_id)
                test_tasks.extend(dirty_recipe_test_tasks)

                build_tasks_created.add(
                    self._create_build_task(
                        obj, dirty_dep_tasks, test_tasks, service_build_tasks
                    )
                )
                if should_push and not (is_msys or is_brew):
                    push_tasks_created.add(
                        self._create_push_task(obj, service_build_tasks)
                    )
            else:
                test_tasks_created.add(
                    self._create_recipe_test_task(
                        obj,
                        dirty_dep_tasks + dirty_recipe_test_tasks,
                        recipe_test_tasks,
                    )
                )
        LOG.info(
            "%s %d test tasks, %d build tasks and %d push tasks",
            self._created_str,
            len(test_tasks_created),
            len(build_tasks_created),
            len(push_tasks_created),
        )

    @classmethod
    def main(cls, args: argparse.Namespace) -> int:
        """Decision procedure.

        Arguments:
            args: Arguments as returned by `parse_args()`

        Returns:
            Shell return code.
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
