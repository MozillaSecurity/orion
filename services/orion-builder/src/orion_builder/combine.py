# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""CLI for Orion builder/combine script"""


import argparse
import sys
from os import getenv
from pathlib import Path
from shutil import rmtree
from tempfile import mkdtemp
from typing import List, Optional

import taskcluster
from taskboot.config import Configuration
from taskboot.docker import Podman
from taskboot.utils import download_artifact, load_artifacts

from .cli import CommonArgs


class CombineArgs(CommonArgs):
    """CLI arguments for Orion combiner"""

    def __init__(self) -> None:
        super().__init__()
        self.parser.add_argument(
            "--output",
            "-o",
            dest="write",
            default=getenv("ARCHIVE_PATH"),
            help="Path to the image tar to output (default: ARCHIVE_PATH)",
        )
        self.parser.add_argument(
            "--build-tool",
            default=getenv("BUILD_TOOL"),
            help="Tool for combining builds into multiarch image (default: BUILD_TOOL)",
            choices={"podman", "docker"},
        )
        self.parser.add_argument(
            "--archs",
            action="append",
            default=getenv("ARCHS", ["amd64"]),
            help="Architectures to be included in the multiarch image",
        )
        self.parser.add_argument(
            "--image",
            default=getenv("IMAGE_NAME"),
            help="Docker image name (without repository, default: IMAGE_NAME)",
        )
        self.parser.add_argument(
            "--load-deps",
            action="store_true",
            help="Pull all images build in dependency tasks into the image store."
            " (default: LOAD_DEPS)",
        )
        self.parser.add_argument(
            "--registry",
            default=getenv("REGISTRY", "docker.io"),
            help="Docker registry to use in images tags (default: docker.io)",
        )
        self.parser.set_defaults(
            build_arg=[],
            cache=str(Path.home() / ".local" / "share"),
            push=False,
        )

    def sanity_check(self, args: argparse.Namespace) -> None:
        super().sanity_check(args)
        args.tag = [args.git_revision, "latest"]

        if args.write is None:
            self.parser.error("--output (or ARCHIVE_PATH) is required!")

        if args.build_tool is None:
            self.parser.error("--build-tool (or BUILD_TOOL) is required!")

        if args.archs is None:
            self.parser.error("--archs is required!")

        if args.image is None:
            self.parser.error("--image (or IMAGE_NAME) is required!")


def main(argv: Optional[List[str]] = None) -> None:
    """Combine entrypoint. Does not return."""

    args = CombineArgs.parse_args(argv)
    service_name = args.service_name
    archs = args.archs
    config = Configuration(argparse.Namespace(secret=None, config=None))
    queue = taskcluster.Queue(config.get_taskcluster_options())
    print(f"Starting the task to combine {service_name} images for archs: {archs}")

    # 1. Load all archs images into podman
    tool = Podman()
    # retrieve image archives from dependency tasks to /images
    image_path = Path(mkdtemp(prefix="image-deps-"))
    try:
        config = Configuration(argparse.Namespace(secret=None, config=None))
        queue = taskcluster.Queue(config.get_taskcluster_options())

        artifacts_ids = load_artifacts(args.task_id, queue, "public/**.tar.zst")

        for task_id, artifact_name in artifacts_ids:
            img = download_artifact(queue, task_id, artifact_name, image_path)
            # load images into the podman image store
            load_result = tool.run(
                [
                    "load",
                    "--input",
                    str(img),
                ],
                text=True,  # TODO: check
            )
            print(load_result)
            img.unlink()
        # TODO: some checks that loaded artifacts = images for specified archs

        # 2. Save loaded images into a single multiarch .tar
        save_result = tool.run(
            ["save", "--multi-image-archive"]
            + [
                f"{args.registry}/mozillasecurity/{service_name}:latest-{arch}"
                for arch in archs
            ]
            + ["--output", f"{service_name}.tar"]  # TODO: check this artifact on TC
        )
        print(save_result)
    finally:
        rmtree(image_path)
    sys.exit(0)
