# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""CLI for Orion builder/push script"""


import argparse

import sys

from taskboot.push import push_artifacts

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

    def sanity_check(self, args: argparse.Namespace) -> None:
        super().sanity_check(args)
        if args.secret is None:
            self.parser.error("--registry-secret (or TASKCLUSTER_SECRET) is required!")

        if args.task_id is None:
            self.parser.error(
                "--task-id (or TASK_ID) is required to load dependency artifacts!"
            )


def main(argv: list[str] | None = None) -> None:
    """Push entrypoint. Does not return."""
    args = PushArgs.parse_args(argv)
    configure_logging(level=args.log_level)
    push_artifacts(None, args)
    sys.exit(0)
