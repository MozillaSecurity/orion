# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""CLI for Orion builder/build script"""


import argparse
import logging
import sys
from os import getenv
from pathlib import Path
from platform import machine
from shutil import rmtree
from typing import List, Optional

from taskboot.build import build_image
from taskboot.target import Target

from .cli import CommonArgs, configure_logging
from .stage_deps import stage_deps

logger = logging.getLogger(__name__)


class BuildArgs(CommonArgs):
    """CLI arguments for Orion builder"""

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
            "--arch",
            default=getenv("ARCH", "amd64"),
            help="Architecture for the image build",
        )
        self.parser.add_argument(
            "--build-tool",
            default=getenv("BUILD_TOOL"),
            help="Tool to use for building (img/dind) (default: BUILD_TOOL)",
            choices={"img", "dind"},
        )
        self.parser.add_argument(
            "--dockerfile",
            default=getenv("DOCKERFILE"),
            help="Path to the Dockerfile (default: Dockerfile)",
        )
        self.parser.add_argument(
            "--build-arg",
            action="append",
            default=[],
            help="Docker build args",
        )
        self.parser.add_argument(
            "--image",
            default=getenv("IMAGE_NAME"),
            help="Docker image name (without registry, default: IMAGE_NAME)",
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

        if not args.load_deps:
            load_deps_env = getenv("LOAD_DEPS")
            if load_deps_env is None or load_deps_env not in {"0", "1"}:
                self.parser.error("LOAD_DEPS must be 0/1")
            if load_deps_env == "1":
                args.load_deps = True

        if args.write is None:
            self.parser.error("--output (or ARCHIVE_PATH) is required!")

        if args.arch is None:
            self.parser.error("--arch (or ARCH) is required!")

        if args.build_tool is None:
            self.parser.error("--build-tool (or BUILD_TOOL) is required!")

        if args.dockerfile is None:
            self.parser.error("--dockerfile (or DOCKERFILE) is required!")

        if args.image is None:
            self.parser.error("--image (or IMAGE_NAME) is required!")

        if args.load_deps and args.task_id is None:
            self.parser.error(
                "--task-id (or TASK_ID) is required to load dependency artifacts!"
            )


def main(argv: Optional[List[str]] = None) -> None:
    """Build entrypoint. Does not return."""
    args = BuildArgs.parse_args(argv)
    base_tag = "latest"
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(machine(), machine())
    assert arch == args.arch
    args.tag = [f"{args.git_revision}-{arch}", base_tag, f"{base_tag}-{arch}"]
    configure_logging(level=args.log_level)
    target = Target(args)
    if args.load_deps:
        stage_deps(args)
    try:
        build_image(target, args)
    finally:
        rmtree(target.dir)
    sys.exit(0)
