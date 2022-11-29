# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Stage build deps Orion builder"""


import argparse
import sys
from pathlib import Path
from shutil import rmtree
from subprocess import PIPE
from tempfile import mkdtemp

import taskcluster
from taskboot.config import Configuration
from taskboot.docker import Podman
from taskboot.utils import download_artifact, load_artifacts


def stage_deps(args: argparse.Namespace) -> None:
    """Pull image dependencies into the `img` store.

    Arguments:
        args: CLI arguments
    """
    tool = Podman()

    # retrieve image archives from dependency tasks to /images
    image_path = Path(mkdtemp(prefix="image-deps-"))
    try:
        config = Configuration(argparse.Namespace(secret=None, config=None))
        queue = taskcluster.Queue(config.get_taskcluster_options())

        # load images into the podman image store
        for task_id, artifact_name in load_artifacts(
            args.task_id, queue, "public/**.tar.zst"
        ):
            img = download_artifact(queue, task_id, artifact_name, image_path)
            image_name = Path(artifact_name).name[: -len(".tar.zst")]
            result = tool.run(
                [
                    "load",
                    "-i",
                    str(img),
                ],
                stdout=PIPE,
                text=True,
            )
            sys.stdout.write(result.stdout)
            img.unlink()
            for line in result.stdout.splitlines():
                if line.startswith("Loaded image: "):
                    loaded_image = line.split(": ", 1)[1]
                    break
            else:
                raise Exception("Couldn't parse image from output")

            latest = f"{args.registry}/mozillasecurity/{image_name}:latest"
            rev = f"{args.registry}/mozillasecurity/{image_name}:{args.git_revision}"

            if rev != loaded_image:
                tool.run(["tag", loaded_image, rev])

            if latest != loaded_image:
                tool.run(["tag", loaded_image, latest])

    finally:
        rmtree(image_path)
