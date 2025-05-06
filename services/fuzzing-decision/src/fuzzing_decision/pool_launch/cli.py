# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import argparse
import logging
import os
import shutil
from typing import List, Optional

from ..common.cli import build_cli_parser
from ..common.util import onerror
from .launcher import PoolLauncher


def main(args: Optional[List[str]] = None) -> None:
    parser = build_cli_parser(prog="fuzzing-pool-launch")
    parser.add_argument(
        "--pool-name",
        type=str,
        help="The target fuzzing pool to create tasks for",
        default=os.environ.get("TASKCLUSTER_FUZZING_POOL"),
    )
    parser.add_argument(
        "--preprocess",
        action="store_true",
        help="Load the pre-process config instead of the normal pool config",
        default=os.environ.get("TASKCLUSTER_FUZZING_PREPROCESS") == "1",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load the configuration, but exit before executing the command.",
    )
    parser.add_argument(
        "--docker",
        metavar="IMAGE",
        help="Launch the fuzzer in given Docker image.",
    )
    parser.add_argument("command", help="docker command-line", nargs=argparse.REMAINDER)
    parsed_args = parser.parse_args(args=args)

    # Setup logger
    logging.basicConfig(level=parsed_args.log_level)

    # Configure workflow using the secret or local configuration
    launcher = PoolLauncher(
        parsed_args.command, parsed_args.pool_name, parsed_args.preprocess
    )
    config = launcher.configure(
        local_path=parsed_args.configuration,
        secret=parsed_args.taskcluster_secret,
        fuzzing_git_repository=parsed_args.git_repository,
        fuzzing_git_revision=parsed_args.git_revision,
    )

    if config is not None:
        # Retrieve remote repository
        launcher.clone(config)
        launcher.load_params()
        if "path" not in config["fuzzing_config"]:
            # we cloned fuzzing-tc-config, clean it up
            shutil.rmtree(launcher.fuzzing_config_dir, onerror=onerror)

    if not parsed_args.dry_run:
        # Execute command
        launcher.exec(in_docker=parsed_args.docker)
    else:

        def _quo_space(part):
            if " " in part:
                return f'"{part}"'
            return part

        # Print what would have been executed
        if parsed_args.docker:
            logging.info(
                "Run: %s",
                " ".join(
                    _quo_space(arg)
                    for arg in launcher.docker_cmd(parsed_args.docker, True)
                ),
            )

        else:
            for key, env in launcher.environment.items():
                if os.environ.get(key) != env:
                    logging.info("Env: %s=%s", key, _quo_space(env))
            logging.info(
                "Command: %s",
                " ".join(_quo_space(arg) for arg in launcher.command),
            )
