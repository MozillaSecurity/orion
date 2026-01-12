# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""CLI for Orion builder/push script"""


import argparse
import logging
import sys
from functools import wraps
from os import getenv
from pathlib import Path
from shutil import rmtree
from subprocess import PIPE, CalledProcessError
from tempfile import mkdtemp
from time import sleep
from typing import Optional

import taskcluster
from taskboot.config import Configuration
from taskboot.docker import Podman
from taskboot.utils import download_artifact, load_artifacts
from yaml import safe_load as yaml_load

from .cli import CommonArgs, configure_logging

LOG = logging.getLogger(__name__)


def retry_call(f, retries=5, initial_delay=5):
    """Retry a call to subprocess.* which raises CalledProcessError."""

    @wraps(f)
    def wrapper(*args, **kwds):
        delay = initial_delay
        for _ in range(retries):
            try:
                return f(*args, **kwds)
            except CalledProcessError:
                LOG.warning("call failed: %s, retrying in %ds...", args, delay)
                sleep(delay)
                delay *= 2
        return f(*args, **kwds)

    return wrapper


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
            type=yaml_load,
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

        if args.archs is None:
            self.parser.error("--archs is required!")

        if args.service_name is None:
            self.parser.error("--service-name is required!")


def main(argv: Optional[list[str]] = None) -> None:
    """Push entrypoint. Does not return."""
    args = PushArgs.parse_args(argv)
    configure_logging(level=args.log_level)
    base_tag = "latest"

    config = Configuration(args)
    queue = taskcluster.Queue(config.get_taskcluster_options())
    index = taskcluster.Index(config.get_taskcluster_options())
    tasks = load_artifacts(args.task_id, queue, "public/**.tar.*")
    assert len(tasks) == 1

    # manually add the task to the TC index.
    # do this now and not via route on the build task so that post-build tests can run
    if args.index is not None:
        LOG.info("Inserting into TC index task: %s", tasks[0][0])
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
        service_name = args.service_name
        archs = args.archs

        tool = Podman()
        image_path = Path(mkdtemp(prefix="image-deps-"))
        task_id, artifact_name = tasks[0]

        try:
            img = download_artifact(queue, task_id, artifact_name, image_path)
            LOG.info(
                "Task %s artifact %s downloaded to: %s", task_id, artifact_name, img
            )
            LOG.debug("Existing images before loading: %s", tool.list_images())

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

            LOG.info(f"Loaded: {load_result}")
            existing_images = tool.list_images()
            LOG.debug("Existing images after loading: %s", existing_images)
            assert all(
                f"{base_tag}-{arch}" in [image["tag"] for image in existing_images]
                for arch in archs
            ), "Could not find scheduled archs in local tags"

            moz_repo = f"mozillasecurity/{service_name}"

            # 2. Create the podman manifest list
            manifest_name = f"docker.io/{moz_repo}:{base_tag}"

            # Remove base_tag from images since manifest list has same tag in the name
            if base_tag in [image["tag"] for image in existing_images]:
                untag_res = tool.run(
                    ["untag", manifest_name, manifest_name], text=True, stdout=PIPE
                )
                LOG.info("Removed tag %s: %s", base_tag, untag_res)
                existing_images = tool.list_images()
                LOG.debug("Existing images after untagging: %s", existing_images)

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

            # 3. Add the loaded images to the manifest
            LOG.debug(
                "Manifest before adding images: %s",
                tool.run(
                    ["manifest", "inspect", manifest_name], text=True, stdout=PIPE
                ).stdout,
            )
            for arch in archs:
                add_result = tool.run(
                    [
                        "manifest",
                        "add",
                        manifest_name,
                        f"containers-storage:docker.io/{moz_repo}:{base_tag}-{arch}",
                    ],
                    text=True,
                    stdout=PIPE,
                )
                LOG.info(f"Added: {add_result}")
            LOG.debug(
                "Manifest after adding images: %s",
                tool.run(
                    ["manifest", "inspect", manifest_name], text=True, stdout=PIPE
                ).stdout,
            )

            # 4. Push the manifest (with images) to docker.io
            retry_call(tool.login)(
                config.docker["registry"],
                config.docker["username"],
                config.docker["password"],
            )

            push_result = retry_call(tool.run)(
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
            LOG.info(f"Push manifest result: {push_result}")
        finally:
            rmtree(image_path)
    sys.exit(0)
