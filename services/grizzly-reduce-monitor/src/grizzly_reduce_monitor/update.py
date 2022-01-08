# _coding=utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Update the original crash in CrashManager following reduction.
"""

from __future__ import annotations

import argparse
from logging import getLogger
import sys

from grizzly.common.fuzzmanager import CrashEntry

from .common import CommonArgParser, ReductionWorkflow, Taskcluster

LOG = getLogger(__name__)


class ReductionUpdater(ReductionWorkflow):
    """
    Attributes:
        crash_id: CrashManager crash ID to update
        quality: Testcase quality to set for crash
        only_if_quality: Only update the crash if the existing quality matches
    """

    def __init__(
        self, crash_id: int, quality: int, only_if_quality: int | None = None
    ) -> None:
        super().__init__()
        self.crash_id = crash_id
        self.quality = quality
        self.only_if_quality = only_if_quality

    def run(self) -> int | None:
        try:
            crash = CrashEntry(self.crash_id)
            if (
                self.only_if_quality is None
                or crash.testcase_quality == self.only_if_quality
            ):
                crash.testcase_quality = self.quality
        except RuntimeError as exc:
            if "status code 404" in str(exc):
                LOG.warning("FuzzManager returned 404, ignoring...")
                return 0
            raise
        return 0

    @staticmethod
    def parse_args(args: list[str] | None = None) -> argparse.Namespace:
        parser = CommonArgParser(prog="grizzly-reduce-tc-update")
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--crash", type=int, help="Crash ID to update.")
        group.add_argument(
            "--crash-from-reduce-task", help="reduce task ID to look for crash ID in."
        )
        parser.add_argument(
            "--quality", type=int, help="Testcase quality to set", required=True
        )
        parser.add_argument(
            "--only-if-quality",
            type=int,
            help="Only change the testcase quality if "
            "the existing quality matches this",
        )
        return parser.parse_args(args=args)

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> ReductionUpdater:
        if args.crash_from_reduce_task:
            LOG.info(
                "Fetching crash ID from reduction task %s", args.crash_from_reduce_task
            )
            task = Taskcluster.get_service("queue").task(args.crash_from_reduce_task)
            crash = int(task["payload"]["env"]["INPUT"])
            LOG.info("=> got crash ID %d", crash)
            return cls(crash, args.quality, args.only_if_quality)
        LOG.info("Resetting crash ID %d", args.crash)
        return cls(args.crash, args.quality, args.only_if_quality)


if __name__ == "__main__":
    sys.exit(ReductionUpdater.main())
