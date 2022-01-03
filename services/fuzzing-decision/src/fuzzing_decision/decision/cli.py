# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import logging
import os

from ..common.cli import build_cli_parser
from .workflow import Workflow


def main() -> None:
    parser = build_cli_parser(prog="fuzzing-decision")
    parser.add_argument(
        "pool_name", type=str, help="The target fuzzing pool to create tasks for"
    )
    parser.add_argument(
        "--task-id",
        type=str,
        help="Taskcluster decision task creating new fuzzing tasks",
        default=os.environ.get("TASK_ID"),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the task group, but exit before creating tasks in Taskcluster.",
    )
    args = parser.parse_args()

    # We need both task & task group information
    if not args.task_id:
        raise Exception("Missing decision task id")

    # Setup logger
    logging.basicConfig(level=args.log_level)

    # Configure workflow using the secret or local configuration
    workflow = Workflow()
    config = workflow.configure(
        local_path=args.configuration,
        secret=args.taskcluster_secret,
        fuzzing_git_repository=args.git_repository,
        fuzzing_git_revision=args.git_revision,
    )

    # Retrieve remote repositories
    workflow.clone(config)

    # Build all task definitions for that pool
    workflow.build_tasks(args.pool_name, args.task_id, config, dry_run=args.dry_run)
