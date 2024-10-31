# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Scheduler for periodic rebuild of Orion tasks"""

from __future__ import annotations

from argparse import Namespace
from datetime import datetime, timezone
from logging import getLogger
from os import getenv

from dateutil.parser import isoparse
from taskcluster.exceptions import TaskclusterRestFailure

from . import ARTIFACTS_EXPIRE, CRON_PERIOD, Taskcluster
from .git import GitRepo
from .orion import Services
from .scheduler import Scheduler

LOG = getLogger(__name__)


class CronScheduler(Scheduler):
    """Decision logic for scheduling Orion build/push tasks in Taskcluster.

    Attributes:
        repo: The Orion repo containing services.
        now: The time to calculate task times from.
        task_group: The taskGroupID to add created tasks to.
        scheduler_id: TC scheduler ID to create tasks in.
        docker_secret: The Taskcluster secret name holding Docker Hub credentials.
        services (Services): The services
        clone_url: Git repo url
        main_branch: Git branch
        dry_run: Perform everything *except* actually queuing tasks in TC.
    """

    def __init__(
        self,
        repo: GitRepo,
        task_group: str,
        scheduler_id: str,
        docker_secret: str,
        clone_url: str,
        branch: str,
        dry_run: bool = False,
    ) -> None:
        """Initialize a Scheduler instance.

        Arguments:
            repo: The Orion repo containing services.
            task_group: The taskGroupID to add created tasks to.
            scheduler_id: TC scheduler ID to create tasks in.
            docker_secret: The Taskcluster secret name holding Docker Hub creds.
            branch: Git main branch
            dry_run: Don't actually queue tasks in Taskcluster.
        """
        self.repo = repo
        self.now = datetime.now(timezone.utc)
        self.task_group = task_group
        self.scheduler_id = scheduler_id
        self.docker_secret = docker_secret
        self.dry_run = dry_run
        self.clone_url = clone_url
        self.main_branch = branch
        self.services = Services(self.repo)

    def _build_index(self, svc_name: str) -> str:
        return f"project.fuzzing.orion.{svc_name}.{self.main_branch}"

    def _clone_url(self) -> str:
        return self.clone_url

    def _commit(self) -> str:
        return self.repo.head()

    def _fetch_ref(self) -> str:
        return self.repo.head()

    def _push_branch(self) -> str:
        return self.main_branch

    def _should_push(self) -> bool:
        return True

    def _skip_tasks(self) -> bool:
        return False

    def mark_services_for_rebuild(self) -> None:
        """Check for services that need to be rebuilt.
        These will have their `dirty` attribute set, which is used to create tasks.
        """
        idx = Taskcluster.get_service("index")
        queue = Taskcluster.get_service("queue")
        # for each service, check taskcluster index
        #   any service that would expire before next run, should be rebuilt
        next_run = self.now + CRON_PERIOD
        for svc in self.services.values():
            if svc.dirty:
                continue
            index_path = f"project.fuzzing.orion.{svc.name}.{self.main_branch}"
            rebuild = False
            try:
                result = idx.findTask(index_path)
            except TaskclusterRestFailure:
                LOG.warning(
                    "%s %s is dirty because %s does not exist",
                    type(svc).__name__,
                    svc.name,
                    index_path,
                )
                rebuild = True
            else:
                result = queue.task(result["taskId"])
                if (
                    min(
                        isoparse(result["deadline"]) + ARTIFACTS_EXPIRE,
                        isoparse(result["expires"]),
                    )
                    < next_run
                ):
                    LOG.warning(
                        "%s %s is dirty because %s expires %s",
                        type(svc).__name__,
                        svc.name,
                        index_path,
                        result["expires"],
                    )
                    rebuild = True
            if rebuild:
                svc.dirty = True
                # propagate dirty bit every time to minimize checking the index
                self.services.propagate_dirty([svc])

    @classmethod
    def main(cls, args: Namespace) -> int:
        """Decision procedure.

        Arguments:
            args: Arguments as returned by `parse_cron_args()`

        Returns:
            Shell return code.
        """
        # get schedulerId from TC queue
        if args.scheduler is None:
            task_obj = Taskcluster.get_service("queue").task(getenv("TASK_ID"))
            scheduler_id = task_obj["schedulerId"]
        else:
            scheduler_id = args.scheduler

        # clone the git repo
        repo = GitRepo(args.clone_repo, args.push_branch, args.push_branch)
        try:
            # create the scheduler
            sched = cls(
                repo,
                args.task_group,
                scheduler_id,
                args.docker_hub_secret,
                args.clone_repo,
                args.push_branch,
                args.dry_run,
            )

            sched.mark_services_for_rebuild()

            # schedule tasks
            sched.create_tasks()
        finally:
            repo.cleanup()

        return 0
