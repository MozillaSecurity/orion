# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""CLI for Orion builder/push script"""


import argparse
import sys
from os import getenv
from typing import List, Optional

import taskcluster
from taskboot.config import Configuration
from taskboot.push import push_artifacts
from taskboot.utils import load_artifacts

from .cli import CommonArgs, configure_logging


class PushArgs(CommonArgs):
    """CLI arguments for Orion pusher"""

    def __init__(self) -> None:
        super().__init__()
        self.parser.set_defaults(
            artifact_filter="public/**.tar.zst",
            exclude_filter=None,
            push_tool="skopeo",
        )
        self.parser.add_argument(
            "--index",
            default=getenv("TASK_INDEX"),
            metavar="NAMESPACE",
            help="Publish task-id at the specified namespace",
        )
        self.parser.add_argument(
            "--skip-docker",
            action="store_true",
            default=bool(int(getenv("SKIP_DOCKER", "0"))),
            help="Don't push Docker image",
        )

    def sanity_check(self, args: argparse.Namespace) -> None:
        super().sanity_check(args)
        if args.secret is None:
            self.parser.error("--registry-secret (or TASKCLUSTER_SECRET) is required!")

        if args.task_id is None:
            self.parser.error(
                "--task-id (or TASK_ID) is required to load dependency artifacts!"
            )


def main(argv: Optional[List[str]] = None) -> None:
    """Push entrypoint. Does not return."""
    args = PushArgs.parse_args(argv)
    configure_logging(level=args.log_level)

    # manually add the task to the TC index.
    # do this now and not via route on the build task so that post-build tests can run
    if args.index is not None:
        config = Configuration(argparse.Namespace(secret=None, config=None))
        queue = taskcluster.Queue(config.get_taskcluster_options())
        index = taskcluster.Index(config.get_taskcluster_options())
        tasks = load_artifacts(args.task_id, queue, "public/**.tar.*")
        assert len(tasks) == 1
        index.insertTask(
            args.index,
            {
                "data": {},
                "expires": queue.task(args.task_id)["expires"],
                "rank": 0,
                "taskId": tasks[0][0],
            },
        )

    if not args.skip_docker:
        push_artifacts(None, args)

    sys.exit(0)
