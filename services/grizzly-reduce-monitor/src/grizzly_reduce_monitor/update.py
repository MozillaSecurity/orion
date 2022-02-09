# _coding=utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Update the original crash in CrashManager following reduction.
"""

import sys
from logging import getLogger

from grizzly.common.fuzzmanager import CrashEntry
from grizzly.common.reporter import Quality

from .common import CommonArgParser, ReductionWorkflow, Taskcluster
from .monitor import GENERIC_PLATFORM

LOG = getLogger(__name__)


class ReductionUpdater(ReductionWorkflow):
    """
    Attributes:
        crash_id (int): CrashManager crash ID to update
        quality (int): Testcase quality to set for crash
        only_if_quality (int): Only update the crash if the existing quality matches
        task_os (str/None): Task OS of reduction (if available)
    """

    def __init__(self, crash_id, quality, only_if_quality=None, task_os=None):
        super().__init__()
        self.crash_id = crash_id
        self.quality = quality
        self.only_if_quality = only_if_quality
        self.task_os = None

    def run(self):
        try:
            crash = CrashEntry(self.crash_id)
            if (
                self.only_if_quality is None
                or crash.testcase_quality == self.only_if_quality
            ):
                if self.quality is None:
                    # set quality based on OS
                    if self.task_os != GENERIC_PLATFORM:
                        crash.testcase_quality = Quality.REQUEST_SPECIFIC
                    else:
                        crash.testcase_quality = Quality.UNREDUCED
                else:
                    crash.testcase_quality = self.quality
        except RuntimeError as exc:
            if "status code 404" in str(exc):
                LOG.warning("FuzzManager returned 404, ignoring...")
                return 0
            raise
        return 0

    @staticmethod
    def parse_args(args=None):
        parser = CommonArgParser(prog="grizzly-reduce-tc-update")
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--crash", type=int, help="Crash ID to update.")
        group.add_argument(
            "--crash-from-reduce-task", help="reduce task ID to look for crash ID in."
        )
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--quality", type=int, help="Testcase quality to set")
        group.add_argument(
            "--auto", action="store_true", help="Automatically set quality based on OS"
        )
        parser.add_argument(
            "--only-if-quality",
            type=int,
            help="Only change the testcase quality if "
            "the existing quality matches this",
        )
        return parser.parse_args(args=args)

    @classmethod
    def from_args(cls, args):
        task_os = None
        if args.crash_from_reduce_task:
            LOG.info(
                "Fetching crash ID from reduction task %s", args.crash_from_reduce_task
            )
            task = Taskcluster.get_service("queue").task(args.crash_from_reduce_task)
            crash = int(task["payload"]["env"]["INPUT"])
            if "windows" in task["workerType"]:
                task_os = "windows"
            elif "macos" in task["workerType"]:
                task_os = "macosx"
            else:
                task_os = "linux"
            LOG.info("=> got crash ID %d", crash)
            return cls(crash, args.quality, args.only_if_quality, task_os)
        LOG.info("Resetting crash ID %d", args.crash)
        return cls(args.crash, args.quality, args.only_if_quality)


if __name__ == "__main__":
    sys.exit(ReductionUpdater.main())
