# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Scheduler for CI tasks"""

from __future__ import annotations

from argparse import Namespace
from datetime import datetime, timezone
from itertools import chain
from json import dumps as json_dump
from logging import getLogger
from os import getenv
from pathlib import Path
from string import Template
from typing import Any

from taskcluster.exceptions import TaskclusterFailure
from taskcluster.utils import slugId, stringDate
from yaml import safe_load as yaml_load

from . import (
    DEADLINE,
    MAX_RUN_TIME,
    PROVISIONER_ID,
    TASKCLUSTER_ROOT_URL,
    WORKER_TYPE,
    WORKER_TYPE_BREW,
    WORKER_TYPE_MSYS,
    Taskcluster,
)
from .ci_matrix import CIMatrix, CISecretKey
from .git import GithubEvent

LOG = getLogger(__name__)
TEMPLATE_PATH = (Path(__file__).parent / "task_templates").resolve()
TEMPLATES = {}
TEMPLATES["linux"] = Template((TEMPLATE_PATH / "ci-linux.yaml").read_text())
TEMPLATES["windows"] = Template((TEMPLATE_PATH / "ci-windows.yaml").read_text())
TEMPLATES["macos"] = Template((TEMPLATE_PATH / "ci-macos.yaml").read_text())
WORKER_TYPES = {}
WORKER_TYPES["linux"] = WORKER_TYPE
WORKER_TYPES["windows"] = WORKER_TYPE_MSYS
WORKER_TYPES["macos"] = WORKER_TYPE_BREW


class CIScheduler:
    """Decision logic for scheduling CI tasks in Taskcluster.

    Attributes:
        project_name: Project name to be used in task metadata.
        github_event: Github event that triggered this run.
        now: Taskcluster time when decision was triggered.
        task_group: Task group to create tasks in.
        scheduler_id: TC scheduler ID to create tasks in.
        dry_run: Calculate what should be created, but don't actually
                 create tasks in Taskcluster.
        matrix: CI job matrix
    """

    def __init__(
        self,
        project_name: str,
        github_event: GithubEvent,
        task_group: str,
        scheduler_id: str,
        matrix: dict[str, Any],
        dry_run: bool = False,
    ) -> None:
        """Initialize a CIScheduler object.

        Arguments:
            project_name: Project name to be used in task metadata.
            github_event: Github event that triggered this run.
            task_group: Task group to create tasks in.
            scheduler_id: TC scheduler ID to create tasks in.
            matrix: CI job matrix
            dry_run: Calculate what should be created, but don't actually
                     create tasks in Taskcluster.
        """
        self.project_name = project_name
        self.github_event = github_event
        self.now = datetime.now(timezone.utc)
        self.task_group = task_group
        self.scheduler_id = scheduler_id
        self.dry_run = dry_run
        assert github_event.event_type is not None
        self.matrix = CIMatrix(
            matrix,
            github_event.branch,
            github_event.event_type,
        )

    def create_tasks(self) -> None:
        """Create CI tasks in Taskcluster."""
        # Don't run push tasks in a PR. These are entirely redundant.
        # Ignore if branch is master/main, in case a PR is merged by push directly.
        # In that case the PR ref would still exist, although the push is to main.
        if self.github_event.event_type == "push" and self.github_event.branch not in {
            "master",
            "main",
        }:
            assert self.github_event.repo is not None
            for ref, commit in self.github_event.repo.refs().items():
                if commit == self.github_event.commit:
                    if ref.startswith("refs/pull/"):
                        LOG.warning("Push in a PR branch. No CI tasks scheduled.")
                        return
        job_tasks = {id(job): slugId() for job in self.matrix.jobs}
        prev_stage: list[str] = []
        for stage in sorted({job.stage for job in self.matrix.jobs}):
            this_stage = []
            for job in self.matrix.jobs:
                if job.stage != stage:
                    continue
                task_id = job_tasks[id(job)]
                this_stage.append(task_id)
                has_deploy_key = any(
                    isinstance(sec, CISecretKey) and sec.hostname is None
                    for sec in chain(self.matrix.secrets, job.secrets)
                )
                if has_deploy_key:
                    clone_repo = self.github_event.ssh_url
                else:
                    clone_repo = self.github_event.http_url
                job_ser = job.serialize()
                assert isinstance(job_ser["secrets"], list)
                job_ser["secrets"].extend(
                    secret.serialize() for secret in self.matrix.secrets
                )
                job_ser["artifacts"].extend(
                    art.serialize() for art in self.matrix.artifacts
                )
                # set CI environment vars for compatibility with eg. codecov
                job_ser["env"].update(
                    {
                        "CI": "true",
                        "CI_BUILD_ID": self.task_group,
                        "CI_BUILD_URL": f"{TASKCLUSTER_ROOT_URL}/tasks/{task_id}",
                        "CI_JOB_ID": task_id,
                        "VCS_BRANCH_NAME": self.github_event.branch,
                        "VCS_COMMIT_ID": self.github_event.commit,
                        "VCS_PULL_REQUEST": str(
                            self.github_event.pull_request or "false"
                        ),
                        "VCS_SLUG": self.github_event.repo_slug,
                        "VCS_TAG": self.github_event.tag or "",
                    }
                )
                kwds = {
                    # need to json.dump twice so we get a string literal in the yaml
                    # template. otherwise (since it's yaml) it would be interpreted
                    # as an object.
                    "ci_job": json_dump(json_dump(job_ser)),
                    "clone_repo": clone_repo,
                    "deadline": stringDate(self.now + DEADLINE),
                    "fetch_ref": self.github_event.fetch_ref,
                    "fetch_rev": self.github_event.commit,
                    "http_repo": self.github_event.http_url,
                    "max_run_time": int(MAX_RUN_TIME.total_seconds()),
                    "name": job.name,
                    "now": stringDate(self.now),
                    "project": self.project_name,
                    "provisioner": PROVISIONER_ID,
                    "scheduler": self.scheduler_id,
                    "task_group": self.task_group,
                    "user": self.github_event.user,
                    "worker": WORKER_TYPES[job.platform],
                }
                if job.platform == "windows":
                    # need to resolve "image" to a task ID where the MSYS
                    # artifact is
                    idx = Taskcluster.get_service("index")
                    result = idx.findTask(f"project.fuzzing.orion.{job.image}.master")
                    kwds["msys_task"] = result["taskId"]
                elif job.platform == "macos":
                    # need to resolve "image" to a task ID where the Homebrew
                    # artifact is
                    idx = Taskcluster.get_service("index")
                    result = idx.findTask(f"project.fuzzing.orion.{job.image}.master")
                    kwds["homebrew_task"] = result["taskId"]
                else:
                    kwds["image"] = job.image
                task = yaml_load(TEMPLATES[job.platform].substitute(**kwds))
                # if any secrets exist, use the proxy and request scopes
                if job.secrets or self.matrix.secrets:
                    task["payload"].setdefault("features", {})
                    task["payload"]["features"]["taskclusterProxy"] = True
                    for sec in chain(job.secrets, self.matrix.secrets):
                        task["scopes"].append(f"secrets:get:{sec.secret}")
                    # ensure scopes are unique
                    task["scopes"] = list(set(task["scopes"]))
                if job.artifacts or self.matrix.artifacts:
                    LOG.debug(
                        "adding %d job and %d matrix artifacts",
                        len(job.artifacts),
                        len(self.matrix.artifacts),
                    )
                    if job.platform == "linux":
                        task["payload"]["artifacts"].update(
                            {
                                art.url: {
                                    "path": art.src,
                                    "type": art.type,
                                }
                                for art in chain(job.artifacts, self.matrix.artifacts)
                            }
                        )
                    else:
                        task["payload"]["artifacts"].extend(
                            {
                                "name": art.url,
                                "path": art.src,
                                "type": art.type,
                            }
                            for art in chain(job.artifacts, self.matrix.artifacts)
                        )
                if not job.require_previous_stage_pass:
                    task["requires"] = "all-resolved"
                task["dependencies"].extend(prev_stage)
                LOG.info("task %s: %s", task_id, task["metadata"]["name"])
                if not self.dry_run:
                    try:
                        Taskcluster.get_service("queue").createTask(task_id, task)
                    except TaskclusterFailure as exc:  # pragma: no cover
                        LOG.error("Error creating CI task: %s", exc)
                        raise

            prev_stage = this_stage

    @classmethod
    def main(cls, args: Namespace) -> int:
        """Decision procedure.

        Arguments:
            args: Arguments as returned by `parse_ci_args()`

        Returns:
            Shell return code.
        """
        # get schedulerId from TC queue
        if args.scheduler is None:
            task_obj = Taskcluster.get_service("queue").task(getenv("TASK_ID"))
            scheduler_id = task_obj["schedulerId"]
        else:
            scheduler_id = args.scheduler

        # get the github event & repo
        evt = GithubEvent.from_taskcluster(
            args.github_action, args.github_event, args.clone_secret
        )
        assert evt.commit_message is not None
        try:
            if "[skip ci]" in evt.commit_message or "[skip tc]" in evt.commit_message:
                LOG.warning(
                    "CI skip command detected in commit message, "
                    "not scheduling any CI tasks"
                )
                args.dry_run = True

            # create the scheduler
            sched = cls(
                args.project_name,
                evt,
                args.task_group,
                scheduler_id,
                args.matrix,
                args.dry_run,
            )

            # schedule tasks
            sched.create_tasks()
        finally:
            evt.cleanup()

        return 0
