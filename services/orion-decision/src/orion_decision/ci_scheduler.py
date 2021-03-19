# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Scheduler for CI tasks"""
from itertools import chain
from logging import getLogger
from pathlib import Path
from string import Template

from taskcluster.exceptions import TaskclusterFailure
from taskcluster.utils import slugId, stringDate
from yaml import safe_load as yaml_load

from . import (
    DEADLINE,
    MAX_RUN_TIME,
    PROVISIONER_ID,
    SCHEDULER_ID,
    WORKER_TYPE,
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
WORKER_TYPES = {}
WORKER_TYPES["linux"] = WORKER_TYPE
WORKER_TYPES["windows"] = WORKER_TYPE_MSYS


class CIScheduler:
    """Decision logic for scheduling CI tasks in Taskcluster."""

    def __init__(
        self, project_name, github_event, now, task_group, matrix, dry_run=False
    ):
        self.project_name = project_name
        self.github_event = github_event
        self.now = now
        self.task_group = task_group
        self.dry_run = dry_run
        self.matrix = CIMatrix(
            matrix,
            github_event.branch,
            github_event.event_type == "release",
        )

    def create_tasks(self):
        """Create CI tasks in Taskcluster.

        Returns:
            None
        """
        job_tasks = {id(job): slugId() for job in self.matrix.jobs}
        prev_stage = []
        for stage in sorted(set(job.stage for job in self.matrix.jobs)):
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
                kwds = {
                    "ci_job": str(job),
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
                    "scheduler": SCHEDULER_ID,
                    "task_group": self.task_group,
                    "user": self.github_event.user,
                    "worker": WORKER_TYPES[job.platform],
                }
                if job.platform == "windows":
                    # need to resolve "image" to a task ID where the MSYS
                    # artifact is
                    idx = Taskcluster.get_service("index")
                    result = idx.findTask(f"project.fuzzing.orion.${job.image}.master")
                    kwds["msys_task"] = result["taskId"]
                else:
                    kwds["image"] = job.image
                task = yaml_load(TEMPLATES[job.platform].substitute(**kwds))
                # if any secrets exist, use the proxy and request scopes
                if job.secrets or self.matrix.secrets:
                    task["payload"].setdefault("features", {})
                    task["payload"]["features"]["taskclusterProxy"] = True
                    for sec in chain(job.secrets, self.matrix.secrets):
                        task["scopes"].append(f"secrets:get:{sec.secret}")
                if not job.require_previous_stage_pass:
                    task["requires"] = "all-resolved"
                task["dependencies"].extend(prev_stage)
                task["payload"]["env"].update(job.env)
                LOG.info("task %s: %s", task_id, task["metadata"]["name"])
                if not self.dry_run:
                    try:
                        Taskcluster.get_service("queue").createTask(task_id, task)
                    except TaskclusterFailure as exc:  # pragma: no cover
                        LOG.error("Error creating CI task: %s", exc)
                        raise

            prev_stage = this_stage

    @classmethod
    def main(cls, args):
        """Decision procedure.

        Arguments:
            args (argparse.Namespace): Arguments as returned by `parse_ci_args()`

        Returns:
            int: Shell return code.
        """
        # get the github event & repo
        evt = GithubEvent.from_taskcluster(args.github_action, args.github_event)
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
                args.now,
                args.task_group,
                args.matrix,
                args.dry_run,
            )

            # schedule tasks
            sched.create_tasks()
        finally:
            evt.cleanup()

        return 0
