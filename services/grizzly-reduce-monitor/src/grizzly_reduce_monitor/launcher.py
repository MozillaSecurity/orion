# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.
"""Launcher to redirect all stdout/stderr to a private log file.
"""


import argparse
import ctypes
import os
import sys
from logging import getLogger
from pathlib import Path
from typing import List, Optional

from .common import CommonArgParser, ReductionWorkflow

LOG = getLogger(__name__)


class PrivateLogLauncher(ReductionWorkflow):
    """Launcher for a fuzzing pool, using docker parameters from a private repo."""

    def __init__(self, command: List[str], log_dir: Path) -> None:
        super().__init__()
        self.command = command.copy()
        self.environment = os.environ.copy()
        self.log_dir = log_dir

    def run(self) -> Optional[int]:
        assert self.command

        LOG.info("Creating private logs directory '%s/'", self.log_dir)
        if self.log_dir.is_dir():
            self.log_dir.chmod(0o777)
        else:
            self.log_dir.mkdir(mode=0o777)
        LOG.info("Redirecting stdout/stderr to %s/live.log", self.log_dir)
        sys.stdout.flush()
        sys.stderr.flush()

        # redirect stdout/stderr to a log file
        # not sure if the assertions would print
        with (self.log_dir / "live.log").open("w") as log:
            result = os.dup2(log.fileno(), 1)
            assert result != -1, "dup2 failed: " + os.strerror(ctypes.get_errno())
            result = os.dup2(log.fileno(), 2)
            assert result != -1, "dup2 failed: " + os.strerror(ctypes.get_errno())

        os.execvpe(self.command[0], self.command, self.environment)

    @staticmethod
    def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
        parser = CommonArgParser(prog="grizzly-reduce-tc-log-private")
        parser.add_argument(
            "--log-dir",
            "-l",
            type=Path,
            help="private log destination (default: /logs)",
            default=Path("/logs"),
        )
        parser.add_argument(
            "command", help="docker command-line", nargs=argparse.REMAINDER
        )
        return parser.parse_args(args=args)

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "PrivateLogLauncher":
        return cls(args.command, args.log_dir)


if __name__ == "__main__":
    sys.exit(PrivateLogLauncher.main())
