# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import argparse
import logging
import os

from ..common.cli import build_cli_parser
from .launcher import PoolLauncher


def main(args=None):
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
    parser.add_argument("command", help="docker command-line", nargs=argparse.REMAINDER)
    args = parser.parse_args(args=args)

    # Setup logger
    logging.basicConfig(level=args.log_level)

    # Configure workflow using the secret or local configuration
    launcher = PoolLauncher(args.command, args.pool_name, args.preprocess)
    config = launcher.configure(
        local_path=args.configuration,
        secret=args.taskcluster_secret,
        fuzzing_git_repository=args.git_repository,
        fuzzing_git_revision=args.git_revision,
    )

    if config is not None:
        # Retrieve remote repository
        launcher.clone(config)
        launcher.load_params()

    if not args.dry_run:
        # Execute command
        launcher.exec()
