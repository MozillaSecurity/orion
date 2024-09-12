# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import re
import sys
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from logging import DEBUG, INFO, WARNING, basicConfig, getLogger
from pathlib import Path

import requests
from Collector.Collector import Collector
from FTB.ProgramConfiguration import ProgramConfiguration
from FTB.Signatures.CrashInfo import CrashInfo
from taskcluster.helper import TaskclusterConfig

LOG = getLogger("ingestor")
Taskcluster = TaskclusterConfig("https://community-tc.services.mozilla.com")


@dataclass
class Ingestor:
    task_id: str
    run_id: int
    tool: str
    dry_run: bool = False

    def run(self) -> int:
        coll = Collector()
        queue = Taskcluster.get_service("queue")
        tc_redirect = queue.getArtifact(
            self.task_id, self.run_id, "public/logs/live.log"
        )
        response = requests.get(tc_redirect["url"], timeout=180)
        log = response.text.splitlines()
        match = re.search(r"Worker Type \([^/]+/([^)]+)\) settings:", log[0])
        assert match is not None, "Unable to parse worker-pool from log!"
        pool = match.group(1)
        if pool.startswith("ci"):
            LOG.warning("Not submitting ci failure")
            return 0
        if pool == "decision":
            LOG.warning("Not submitting decision failure")
            return 0
        if pool.startswith("grizzly-reduce"):
            LOG.warning("Not submitting grizzly-reduce failure")
            return 0
        worker_settings = {}
        for line_no, line in enumerate(log):
            if (start_idx := line.find("=== Task Starting ===")) >= 0:
                worker_settings = json.loads(
                    "".join(line[start_idx:] for line in log[1 : line_no - 1])
                )
                break
        assert worker_settings, "Unable to find worker settings in log!"
        pc = ProgramConfiguration(
            "generic-worker",
            worker_settings["generic-worker"]["go-arch"],
            worker_settings["generic-worker"]["go-os"],
            worker_settings["generic-worker"]["version"],
        )
        crash = CrashInfo.fromRawCrashData(stdout=[], stderr=log, configuration=pc)
        metadata = {
            "instance-type": worker_settings["instance-type"],
            "worker-pool": pool,
        }
        if not self.dry_run:
            coll.submit(crash, metaData=metadata)
        else:
            LOG.info("would submit:")
            LOG.info("%s", crash)
            LOG.info("with metadata:")
            LOG.info("%s", json.dumps(metadata, indent=2, sort_keys=True))
        return 0

    @staticmethod
    def ensure_credentials() -> None:
        """Ensure necessary FM credentials exist.

        This checks:
            ~/.fuzzmanagerconf  -- fuzzmanager credentials
        """
        # get fuzzmanager config from taskcluster
        conf_path = Path.home() / ".fuzzmanagerconf"
        if not conf_path.is_file():
            key = Taskcluster.load_secrets("project/fuzzing/fuzzmanagerconf")["key"]
            conf_path.write_text(key)
            conf_path.chmod(0o400)

    @staticmethod
    def parse_args(args: list[str] | None = None) -> Namespace:
        parser = ArgumentParser(prog="ingestor")
        parser.add_argument(
            "--task-id", help="task ID to ingest logs from", required=True
        )
        parser.add_argument(
            "--run-id", type=int, help="run ID to ingest logs from", required=True
        )
        parser.add_argument(
            "--tool",
            help="Toolname to report logs to in FM (default: %(default)s)",
            default="taskcluster",
        )
        parser.add_argument(
            "--dry-run",
            "-s",
            help="Download and parse log, but don't submit to FM",
            action="store_true",
        )

        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--quiet",
            "-q",
            dest="log_level",
            action="store_const",
            const=WARNING,
            help="Be less verbose",
        )
        group.add_argument(
            "--verbose",
            "-v",
            dest="log_level",
            action="store_const",
            const=DEBUG,
            help="Be more verbose",
        )
        parser.set_defaults(log_level=INFO)

        return parser.parse_args(args)

    @classmethod
    def main(cls, args: Namespace | None = None) -> int:
        """Main entrypoint for reduction scripts."""
        if args is None:
            args = cls.parse_args()

        assert args is not None
        # Setup logger
        getLogger("taskcluster").setLevel(WARNING)
        getLogger("urllib3").setLevel(WARNING)
        basicConfig(level=args.log_level)

        # Setup credentials if needed
        if not args.dry_run:
            cls.ensure_credentials()

        return cls(args.task_id, args.run_id, args.tool, args.dry_run).run()


if __name__ == "__main__":
    sys.exit(Ingestor.main())
