# _coding=utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Check CrashManager for reducible crashes, and queue them in Taskcluster.
"""

import os
import sys
from collections import namedtuple
from datetime import datetime, timedelta
from logging import getLogger

from grizzly.common.reporter import FuzzManagerReporter
from taskcluster.exceptions import TaskclusterFailure
from taskcluster.utils import slugId, stringDate

from .common import CommonArgParser, CrashManager, ReductionWorkflow, Taskcluster

LOG = getLogger(__name__)

# GENERIC_PLATFORM is used as a first pass for all unreduced test cases.
GENERIC_PLATFORM = "linux"

TC_QUEUES = {
    # "android": "grizzly-reduce-android",
    "linux": "grizzly-reduce-worker",
    # "macosx": "grizzly-reduce-macos",
    # "windows": "grizzly-reduce-windows",
}

TOOL_LIST_SECRET = "project/fuzzing/grizzly-reduce-tool-list"
OWNER_EMAIL = "truber@mozilla.com"
REDUCTION_MAX_RUN_TIME = timedelta(hours=6)
REDUCTION_DEADLINE = timedelta(days=1)
REDUCTION_EXPIRES = timedelta(weeks=2)
SCHEDULER_ID = "fuzzing"
PROVISIONER_ID = "proj-fuzzing"
DESCRIPTION = """*DO NOT EDIT* - This resource is configured automatically.

Fuzzing workers generated by decision task"""


ReducibleCrash = namedtuple(
    "ReducibleCrash", "crash, bucket, tool, description, os, quality"
)


def _fuzzmanager_get_crashes(tool_list):
    """This function is responsible for getting CrashInfo objects to try to reduce
    from FuzzManager.

    Yields all crashes where:
        quality = 5 OR quality = 6
        AND
        tool is in tool_list
        AND
            crash is unbucketed
            OR
            bucket quality is 5 or 6

    Note that a bucket may have a quality=0 testcase from a tool which isn't in
    tool_list, and this would prevent any other testcases in the bucket
    from, being reduced.

    Arguments:
        tool_list (list): List of tools to monitor for reduction.

    Yields:
        ReducibleCrash: All the info needed to queue a crash for reduction
    """
    assert isinstance(tool_list, list)
    srv = CrashManager()

    # get unbucketed crashes with specified quality
    for crash in srv.list_crashes(
        {
            "op": "AND",
            "bucket__isnull": True,
            "testcase__quality__in": [
                FuzzManagerReporter.QUAL_UNREDUCED,
                FuzzManagerReporter.QUAL_REQUEST_SPECIFIC,
            ],
            "tool__name__in": tool_list,
        }
    ):
        yield ReducibleCrash(
            crash=crash["id"],
            bucket=None,
            tool=crash["tool"],
            description=crash["shortSignature"],
            os=crash["os"],
            quality=crash["testcase_quality"],
        )

    # get list of buckets with best testcase with specified quality
    for bucket in srv.list_buckets(
        {
            "op": "AND",
            "crashentry__tool__name__in": tool_list,
        }
    ):
        if bucket["best_quality"] not in {
            FuzzManagerReporter.QUAL_UNREDUCED,
            FuzzManagerReporter.QUAL_REQUEST_SPECIFIC,
        }:
            continue
        # for each bucket+tool, get crashes with specified quality
        for crash in srv.list_crashes(
            {
                "op": "AND",
                "bucket_id": bucket["id"],
                "testcase__quality__in": [
                    FuzzManagerReporter.QUAL_UNREDUCED,
                    FuzzManagerReporter.QUAL_REQUEST_SPECIFIC,
                ],
                "tool__name__in": tool_list,
            }
        ):
            yield ReducibleCrash(
                crash=crash["id"],
                bucket=bucket["id"],
                tool=crash["tool"],
                description=bucket["shortDescription"],
                os=crash["os"],
                quality=crash["testcase_quality"],
            )


class ReductionMonitor(ReductionWorkflow):
    """Scan CrashManager to see if there are any crashes which should be reduced.

    Attributes:
        dry_run (bool): Scan CrashManager, but don't queue any work in Taskcluster
                        nor update any state in CrashManager.
        tool_list (list(str)): List of Grizzly tools to look for crashes under.
    """

    def __init__(self, dry_run=False, tool_list=None):
        super().__init__()
        self.dry_run = dry_run
        if self.dry_run:
            LOG.warning("*** DRY RUN -- SIMULATION ONLY ***")
        if not tool_list:
            LOG.warning("No tools specified on CLI, fetching from Taskcluster")
            tool_list = Taskcluster.load_secrets(TOOL_LIST_SECRET)["tools"]
        self.tool_list = list(tool_list or [])

    def queue_reduction_task(self, os_name, crash_id):
        """Queue a reduction task in Taskcluster.

        Arguments:
            os_name (str): The OS to schedule the task for.
            crash_id (int): The CrashManager crash ID to reduce.

        Returns:
            None
        """
        if self.dry_run:
            return
        dest_queue = TC_QUEUES[os_name]
        my_task_id = os.environ.get("TASK_ID")
        task_id = slugId()
        now = datetime.utcnow()
        task = {
            "taskGroupId": my_task_id,
            "dependencies": [],
            "created": stringDate(now),
            "deadline": stringDate(now + REDUCTION_DEADLINE),
            "expires": stringDate(now + REDUCTION_EXPIRES),
            "extra": {},
            "metadata": {
                "description": DESCRIPTION,
                "name": f"Reduce fuzzing crash {crash_id} for {os_name}",
                "owner": OWNER_EMAIL,
                "source": "https://github.com/MozillaSecurity/grizzly",
            },
            "payload": {
                "artifacts": {
                    "project/fuzzing/private/logs": {
                        "expires": stringDate(now + REDUCTION_EXPIRES),
                        "path": "/logs/",
                        "type": "directory",
                    }
                },
                "cache": {},
                "capabilities": {
                    "devices": {
                        "hostSharedMemory": True,
                        "loopbackAudio": True,
                    },
                },
                "env": {
                    "CORPMAN": "reducer",
                    "CREDSTASH_SECRET": "credstash-aws-auth",
                    "FUZZING_CPU_COUNT": "0",  # force single instance/task
                    "IGNORE": "log-limit memory timeout",
                    "MEM_LIMIT": "7000",
                    "INPUT": str(crash_id),
                    "TIMEOUT": "60",
                },
                "features": {"taskclusterProxy": True},
                "image": {
                    "type": "indexed-image",
                    "namespace": "project.fuzzing.orion.grizzly.master",
                    "path": "public/grizzly.tar.zst",
                },
                "maxRunTime": REDUCTION_MAX_RUN_TIME.total_seconds(),
            },
            "priority": "high",
            "provisionerId": PROVISIONER_ID,
            "workerType": dest_queue,
            "retries": 5,
            "routes": [],
            "schedulerId": SCHEDULER_ID,
            "scopes": [
                "docker-worker:capability:device:hostSharedMemory",
                "docker-worker:capability:device:loopbackAudio",
                "secrets:get:project/fuzzing/credstash-aws-auth",
            ],
            "tags": {},
        }
        queue = Taskcluster.get_service("queue")
        LOG.info("Creating task %s: %s", task_id, task["metadata"]["name"])
        try:
            queue.createTask(task_id, task)
        except TaskclusterFailure as exc:
            LOG.error("Error creating task: %s", exc)
            return
        LOG.info("Marking %d Q4 (in progress)", crash_id)
        CrashManager().update_testcase_quality(crash_id, 4)

    def run(self):
        queued = set()
        srv = CrashManager()

        LOG.info("starting poll of FuzzManager")
        # mark all Q=6 crashes that we don't have a queue for, move them to Q=10
        for crash in srv.list_crashes(
            {
                "op": "AND",
                "testcase__quality": FuzzManagerReporter.QUAL_REQUEST_SPECIFIC,
                "tool__name__in": list(self.tool_list),
                "_": {
                    "op": "NOT",
                    "os__name__in": list(set(TC_QUEUES) - {GENERIC_PLATFORM}),
                },
            }
        ):
            LOG.info(
                "crash %d updating Q%d => Q%d, platform is %s",
                crash["id"],
                FuzzManagerReporter.QUAL_REQUEST_SPECIFIC,
                FuzzManagerReporter.QUAL_NOT_REPRODUCIBLE,
                crash["os"],
            )
            if not self.dry_run:
                srv.update_testcase_quality(
                    crash["id"], FuzzManagerReporter.QUAL_NOT_REPRODUCIBLE
                )

        # get all crashes for Q=5 and project in tool_list
        for reduction in _fuzzmanager_get_crashes(self.tool_list):
            sig = (
                f"{reduction.tool}:{reduction.bucket!r}:"
                f"{reduction.description}:{reduction.quality!r}"
            )

            if sig in queued:
                continue
            queued.add(sig)

            LOG.info("queuing %d for %s", reduction.crash, sig)
            if reduction.quality == FuzzManagerReporter.QUAL_UNREDUCED:
                # perform first pass with generic platform reducer on Q5
                os_name = GENERIC_PLATFORM
            elif reduction.os in TC_QUEUES and reduction.os != GENERIC_PLATFORM:
                # move Q6 to platform specific queue if it exists
                os_name = reduction.os
            else:
                LOG.info(
                    "> updating Q%d => Q%d, platform is %s",
                    reduction.quality,
                    FuzzManagerReporter.QUAL_NOT_REPRODUCIBLE,
                    reduction.os,
                )
                if not self.dry_run:
                    srv.update_testcase_quality(
                        reduction.crash, FuzzManagerReporter.QUAL_NOT_REPRODUCIBLE
                    )
                continue
            self.queue_reduction_task(os_name, reduction.crash)
        LOG.info("finished polling FuzzManager")
        return 0

    @staticmethod
    def parse_args(args=None):
        parser = CommonArgParser(prog="grizzly-reduce-tc-monitor")
        parser.add_argument(
            "-n",
            "--dry-run",
            action="store_true",
            help="Don't schedule tasks or update crashes in CrashManager, only "
            "print what would be done.",
        )
        parser.add_argument(
            "--tool-list", nargs="+", help="Tools to search for reducible crashes"
        )
        return parser.parse_args(args=args)

    @classmethod
    def from_args(cls, args):
        return cls(dry_run=args.dry_run, tool_list=args.tool_list)


if __name__ == "__main__":
    sys.exit(ReductionMonitor.main())
