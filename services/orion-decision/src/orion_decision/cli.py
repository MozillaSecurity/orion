# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Command line checks retained for Orion's local service graph."""

from __future__ import annotations

import sys
from argparse import ArgumentParser, Namespace
from locale import LC_ALL, setlocale
from logging import DEBUG, INFO, WARN, basicConfig, getLogger
from pathlib import Path

from .git import GitRepo
from .orion import Services


def configure_logging(level: int = INFO) -> None:
    """Configure a log handler.

    Arguments:
        level: Log verbosity constant from the `logging` module.
    """
    setlocale(LC_ALL, "")
    basicConfig(format="[%(levelname).1s] %(message)s", level=level)
    if level == DEBUG:
        getLogger("taskcluster").setLevel(INFO)
        getLogger("urllib3").setLevel(INFO)


def _define_logging_args(parser: ArgumentParser) -> None:
    log_levels = parser.add_mutually_exclusive_group()
    log_levels.add_argument(
        "--quiet",
        "-q",
        dest="log_level",
        action="store_const",
        const=WARN,
        help="Show less logging output.",
    )
    log_levels.add_argument(
        "--verbose",
        "-v",
        dest="log_level",
        action="store_const",
        const=DEBUG,
        help="Show more logging output.",
    )
    parser.set_defaults(
        log_level=INFO,
    )


def parse_check_args(argv: list[str] | None = None) -> Namespace:
    """Parse command-line arguments for check.

    Arguments:
        argv: Argument list, or sys.argv if None.

    Returns:
        parsed result
    """
    parser = ArgumentParser(prog="orion-check")
    _define_logging_args(parser)
    parser.add_argument(
        "repo",
        type=Path,
        help="Orion repo root to scan for service files",
    )
    parser.add_argument(
        "changed",
        type=Path,
        nargs="*",
        help="Changed path(s)",
    )
    return parser.parse_args(argv)


def check() -> None:
    """Service definition check entrypoint."""
    args = parse_check_args()
    configure_logging(level=args.log_level)
    services = Services(GitRepo.from_existing(args.repo))
    services.mark_changed_dirty([args.repo / path for path in args.changed])
    sys.exit(0)
