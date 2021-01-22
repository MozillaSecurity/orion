# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import argparse
import logging
import os
import pathlib


def build_cli_parser(*args, **kwargs):
    parser = argparse.ArgumentParser(*args, **kwargs)
    parser.add_argument(
        "--taskcluster-secret",
        type=str,
        help="Taskcluster Secret path for configuration",
        default=os.environ.get("TASKCLUSTER_SECRET"),
    )
    parser.add_argument(
        "--configuration",
        type=pathlib.Path,
        help="Local configuration file replacing Taskcluster secrets for fuzzing",
    )
    parser.add_argument(
        "--git-repository",
        help="A git repository containing the Fuzzing configuration",
        default=os.environ.get("FUZZING_GIT_REPOSITORY"),
    )
    parser.add_argument(
        "--git-revision",
        help="A git revision for the fuzzing git repository",
        default=os.environ.get("FUZZING_GIT_REVISION"),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--quiet",
        "-q",
        dest="log_level",
        action="store_const",
        const=logging.WARNING,
        help="Be less verbose",
    )
    group.add_argument(
        "--verbose",
        "-v",
        dest="log_level",
        action="store_const",
        const=logging.DEBUG,
        help="Be more verbose",
    )
    parser.set_defaults(log_level=logging.INFO)
    return parser
