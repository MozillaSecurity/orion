# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""CLI for Orion scheduler"""

from __future__ import annotations

import sys
from argparse import ArgumentParser, Namespace
from locale import LC_ALL, setlocale
from logging import DEBUG, INFO, WARN, basicConfig, getLogger
from os import chdir, getenv
from os import environ as os_environ
from pathlib import Path
from shutil import which
from subprocess import run

from yaml import safe_load as yaml_load

from .ci_check import check_matrix
from .ci_matrix import CISecretEnv, CISecretKey, MatrixJob
from .ci_scheduler import CIScheduler
from .cron import CronScheduler
from .git import GitRepo
from .orion import Services
from .scheduler import Scheduler

LOG = getLogger(__name__)


def configure_logging(level: int = INFO) -> None:
    """Configure a log handler.

    Arguments:
        level: Log verbosity constant from the `logging` module.
    """
    setlocale(LC_ALL, "")
    basicConfig(format="[%(levelname).1s] %(message)s", level=level)
    if level == DEBUG:
        # no need to ever see lower than INFO for third-parties
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


def _define_github_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--github-event",
        default=getenv("GITHUB_EVENT", "{}"),
        type=yaml_load,
        help="The raw Github Webhook event.",
    )
    parser.add_argument(
        "--github-action",
        default=getenv("GITHUB_ACTION"),
        choices={"github-push", "github-pull-request", "github-release"},
        help="The event action that triggered this decision.",
    )


def _sanity_check_github_args(parser: ArgumentParser, result: Namespace) -> None:
    if result.github_action is None:
        parser.error("--github-action (or GITHUB_ACTION) is required!")

    if not result.github_event:
        parser.error("--github-event (or GITHUB_EVENT) is required!")
    assert isinstance(result.github_event, dict)
    assert all(isinstance(key, str) for key in result.github_event)


def _define_decision_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--task-group",
        default=getenv("TASK_ID"),
        help="Create tasks in this task group (default: TASK_ID).",
    )
    parser.add_argument(
        "--scheduler",
        default=None,
        help="Create tasks with this scheduler ID (default: fetch from TaskCluster).",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Do not queue tasks in Taskcluster, only calculate what would be done.",
    )


def parse_args(argv: list[str] | None = None) -> Namespace:
    """Parse command-line arguments.

    Arguments:
        argv: Argument list, or sys.argv if None.

    Returns:
        parsed result
    """
    parser = ArgumentParser(prog="decision")
    _define_logging_args(parser)
    _define_github_args(parser)
    _define_decision_args(parser)

    parser.add_argument(
        "--push-branch",
        default=getenv("PUSH_BRANCH", "master"),
        help="Push to Docker Hub if push event is on this branch " "(default: master).",
    )
    parser.add_argument(
        "--docker-hub-secret",
        default=getenv("DOCKER_HUB_SECRET"),
        help="Taskcluster secret holding Docker Hub credentials for push.",
    )

    result = parser.parse_args(argv)
    _sanity_check_github_args(parser, result)
    return result


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


def parse_ci_check_args(argv: list[str] | None = None) -> Namespace:
    """Parse command-line arguments for CI check.

    Arguments:
        argv: Argument list, or sys.argv if None.

    Returns:
        parsed result
    """
    parser = ArgumentParser(prog="ci-check")
    _define_logging_args(parser)
    parser.add_argument(
        "changed",
        type=Path,
        nargs="*",
        help="Changed path(s)",
    )
    return parser.parse_args(argv)


def parse_ci_launch_args(argv: list[str] | None = None) -> Namespace:
    """Parse command-line arguments for CI launch.

    Arguments:
        argv: Argument list, or sys.argv if None.

    Returns:
        parsed result
    """
    parser = ArgumentParser(prog="ci-launch")
    _define_logging_args(parser)
    parser.add_argument(
        "--fetch-ref",
        default=getenv("FETCH_REF"),
        help="Git reference to fetch",
    )
    parser.add_argument(
        "--fetch-rev",
        default=getenv("FETCH_REV"),
        help="Git revision to checkout",
    )
    parser.add_argument(
        "--clone-repo",
        default=getenv("CLONE_REPO"),
        help="Git repository to clone",
    )
    parser.add_argument(
        "--job",
        default=getenv("CI_JOB"),
        help="The CI job object",
    )
    result = parser.parse_args(argv)
    if not result.job:
        parser.error("--job (or CI_JOB) is required!")
    if not result.fetch_ref:
        parser.error("--fetch-ref (or FETCH_REF) is required!")
    if not result.fetch_rev:
        parser.error("--fetch-rev (or FETCH_REV) is required!")
    if not result.clone_repo:
        parser.error("--clone-repo (or CLONE_REPO) is required!")
    result.job = MatrixJob.from_json(result.job)

    return result


def parse_ci_args(argv: list[str] | None = None) -> Namespace:
    """Parse command-line arguments for CI.

    Arguments:
        argv: Argument list, or sys.argv if None.

    Returns:
        parsed result
    """
    parser = ArgumentParser(prog="ci-decision")
    _define_logging_args(parser)
    _define_github_args(parser)
    _define_decision_args(parser)

    parser.add_argument(
        "--matrix",
        default=getenv("CI_MATRIX", "{}"),
        type=yaml_load,
        help="The build matrix. TODO: document",
    )
    parser.add_argument(
        "--project-name",
        default=getenv("PROJECT_NAME"),
        help="The human readable project name for CI",
    )
    parser.add_argument(
        "--clone-secret",
        default=getenv("CLONE_SECRET"),
        help="Use Taskcluster secret to clone repo via ssh",
    )

    result = parser.parse_args(argv)
    _sanity_check_github_args(parser, result)

    if not result.matrix:
        parser.error("--matrix (or CI_MATRIX) is required!")
    assert isinstance(result.matrix, dict)
    assert all(isinstance(key, str) for key in result.matrix)

    if not result.project_name:
        parser.error("--project-name (or PROJECT_NAME) is required!")

    return result


def parse_cron_args(argv: list[str] | None = None) -> Namespace:
    """Parse command-line arguments for cron decision.

    Arguments:
        argv: Argument list, or sys.argv if None.

    Returns:
        parsed result
    """
    parser = ArgumentParser(prog="cron-decision")
    _define_logging_args(parser)
    _define_decision_args(parser)

    parser.add_argument(
        "--clone-repo",
        default=getenv("CLONE_REPO"),
        help="Git repository to clone",
    )
    parser.add_argument(
        "--push-branch",
        default=getenv("PUSH_BRANCH", "master"),
        help="Push to Docker Hub if push event is on this branch " "(default: master).",
    )
    parser.add_argument(
        "--docker-hub-secret",
        default=getenv("DOCKER_HUB_SECRET"),
        help="Taskcluster secret holding Docker Hub credentials for push.",
    )

    return parser.parse_args(argv)


def ci_main() -> None:
    """CI decision entrypoint."""
    args = parse_ci_args()
    configure_logging(level=args.log_level)
    if args.clone_secret:
        secret = CISecretKey(args.clone_secret, "key")
        LOG.info("Cloning using secret: %s", secret.secret)
        secret.write()
    sys.exit(CIScheduler.main(args))


def ci_launch() -> None:
    """CI task entrypoint."""
    args = parse_ci_launch_args()
    configure_logging(level=args.log_level)
    # copy environment and filter out `Administrator` paths
    # which we shouldn't have access to
    # this broke tox either in 4.15 or when some permission thing changed
    # in the Windows AMI
    env = os_environ.copy()
    if "PATH" in env:
        env["PATH"] = ";".join(
            p
            for p in env["PATH"].split(";")
            if p
            # check if path starts with `\Users\Administrator\`
            # skipping drive (parts[0]) and ignoring case
            # this only works on English machines ¯\_(ツ)_/¯
            and [pt.casefold() for pt in Path(p).resolve().parts[1:3]]
            != ["users", "administrator"]
        )
    # fetch secrets
    LOG.info("Fetching %d secrets", len(args.job.secrets))
    for secret in args.job.secrets:
        LOG.info("  secret: %s", secret.secret)
        if isinstance(secret, CISecretEnv):
            env[secret.name] = secret.get_secret_data()
            assert isinstance(env[secret.name], str), (
                f"expected secret '{secret.secret}' to be a string "
                f"(got {type(env[secret.name]).__name__})... missing `key`?"
            )
        else:
            secret.write()
    # clone repo
    LOG.info("Cloning repo: %s @ %s", args.clone_repo, args.fetch_rev)
    repo = GitRepo(args.clone_repo, args.fetch_ref, args.fetch_rev)
    assert repo.path is not None
    chdir(repo.path)
    # update env
    env.update(args.job.env)
    # update command
    LOG.info("Running %r", args.job.script)
    if args.job.platform == "windows" and not Path(args.job.script[0]).is_file():
        binary = which(args.job.script[0])
        assert (
            binary is not None
        ), f"Couldn't resolve script executable: {args.job.script[0]}"
        args.job.script[0] = binary
    sys.exit(run(args.job.script, env=env, check=True).returncode)


def ci_check() -> None:
    """CI build matrix check entrypoint."""
    args = parse_ci_check_args()
    configure_logging(level=args.log_level)
    check_matrix(args)
    sys.exit(0)


def check() -> None:
    """Service definition check entrypoint."""
    args = parse_check_args()
    configure_logging(level=args.log_level)
    svcs = Services(GitRepo.from_existing(args.repo))
    svcs.mark_changed_dirty([args.repo / file for file in args.changed])
    sys.exit(0)


def cron_main() -> None:
    """Cron decision entrypoint. Does not return."""
    args = parse_cron_args()
    configure_logging(level=args.log_level)
    sys.exit(CronScheduler.main(args))


def main() -> None:
    """Decision entrypoint. Does not return."""
    args = parse_args()
    configure_logging(level=args.log_level)
    sys.exit(Scheduler.main(args))
