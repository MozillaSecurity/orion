# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""CLI for Orion builder/push script"""


import argparse
import logging
import sys
from ast import literal_eval
from os import getenv
from pathlib import Path
from subprocess import PIPE
from tempfile import mkdtemp
from typing import List, Optional

import taskcluster
from taskboot.config import Configuration
from taskboot.docker import Podman
from taskboot.utils import download_artifact, load_artifacts

from .cli import CommonArgs, configure_logging

LOG = logging.getLogger(__name__)


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
            "--archs",
            action="append",
            default=getenv("ARCHS", ["amd64"]),
            help="Architectures to be included in the multiarch image",
        )
        self.parser.add_argument(
            "--index",
            default=getenv("TASK_INDEX"),
            metavar="NAMESPACE",
            help="Publish task-id at the specified namespace",
        )
        self.parser.add_argument(
            "--service-name",
            action="append",
            default=getenv("SERVICE_NAME"),
            help="Name of the service of the multiarch image",
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
        LOG.info("Inserting into TC index task: ", tasks[0][0])
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
        config = Configuration(args)
        tool = Podman()  # push_artifacts in push.py uses skopeo by default

        queue = taskcluster.Queue(config.get_taskcluster_options())
        artifacts_ids = load_artifacts(
            args.task_id, queue, "public/**.tar.zst"
        )  # must be a single build/combine artifact
        artifact_id, artifact_name = artifacts_ids[0]
        image_path = Path(mkdtemp(prefix="image-deps-"))
        img = download_artifact(queue, artifact_id, artifact_name, image_path)

        if isinstance(args.archs, list):  # TODO: remove
            print(f"ARCHS list deserialized: {args.archs}")
            archs = args.archs
        elif isinstance(args.archs, str):
            try:
                archs = literal_eval(args.archs)
            except Exception as e:
                print("Eval failed: ", e)
                print("Converting string manually")
                archs = args.archs.strip("[]").replace("'", "").split(", ")
            print(f"YAML list fail, making from string {args.archs} to {archs}")
        else:
            LOG.error("ARCHS is not a list or string: ", args.archs)

        # 1. Load image/s artifact into the podman image store
        load_result = tool.run(
            [
                "load",
                "--input",
                str(img),
            ],
            text=True,
            stdout=PIPE,
        )
        LOG.info("Load result: ", load_result)
        img.unlink()
        service_name = args.service_name
        MOZ_REPO = f"mozillasecurity/{service_name}"
        AS_REPO = f"asuleimanov/{service_name}"

        manifest_name = f"docker.io/{AS_REPO}:latest"  # TODO: change to MOZ
        create_result = tool.run(
            [
                "manifest",
                "create",
                "--amend",
                manifest_name,
            ],
            text=True,
            stdout=PIPE,
        )
        LOG.info(f"Manifest created: {create_result}")
        # 3. Podman manifest add images
        for arch in archs:
            add_result = tool.run(
                [
                    "manifest",
                    "add",
                    manifest_name,
                    f"containers-storage:docker.io/{MOZ_REPO}:latest-{arch}",
                ],
                text=True,
                stdout=PIPE,
            )
            LOG.info(f"{add_result = }")
        # 4. Podman manifest push
        tool.login(
            config.docker["registry"],
            config.docker["username"],
            config.docker["password"],
        )
        push_result = tool.run(
            [
                "manifest",
                "push",
                "--all",
                manifest_name,
                f"docker://{manifest_name}",
            ],
            text=True,
            stdout=PIPE,
        )
        print(f"Push manifest result: {push_result}")

    sys.exit(0)
