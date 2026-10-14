# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Tests for the retained service graph check command and CLI entrypoints."""

import os
import subprocess
import sys
from logging import DEBUG
from pathlib import Path
from unittest.mock import call

import pytest
from pytest_mock import MockerFixture

from orion_decision.cli import (
    check,
    configure_logging,
    parse_check_args,
)

ROOT = Path(__file__).parents[3]
PACKAGE_PATH = ROOT / "services/orion-decision"
SOURCE_PATH = PACKAGE_PATH / "src"


def _run_python(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(SOURCE_PATH), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_check_args() -> None:
    """test service check argument parsing"""
    with pytest.raises(SystemExit):
        parse_check_args([])
    result = parse_check_args(["path"])
    assert result.repo == Path("path")


def test_logging_init(mocker: MockerFixture) -> None:
    """test logging initializer"""
    locale = mocker.patch("orion_decision.cli.setlocale", autospec=True)
    log_init = mocker.patch("orion_decision.cli.basicConfig", autospec=True)
    configure_logging(level=DEBUG)
    assert locale.call_count == 1
    assert log_init.call_count == 1
    assert log_init.call_args == call(
        format="[%(levelname).1s] %(message)s", level=DEBUG
    )


def test_check(mocker: MockerFixture) -> None:
    """test CLI check entrypoint"""
    log_init = mocker.patch("orion_decision.cli.configure_logging", autospec=True)
    parser = mocker.patch("orion_decision.cli.parse_check_args", autospec=True)
    repo = mocker.patch("orion_decision.cli.GitRepo", autospec=True)
    services = mocker.patch("orion_decision.cli.Services", autospec=True)
    with pytest.raises(SystemExit) as exc:
        check()
    assert log_init.call_count == 1
    assert parser.call_count == 1
    assert log_init.call_args == call(level=parser.return_value.log_level)
    assert repo.from_existing.call_count == 1
    assert repo.from_existing.call_args == call(parser.return_value.repo)
    assert services.call_count == 1
    assert services.call_args == call(repo.from_existing.return_value)
    assert exc.value.code == 0


def test_orion_check_help_entrypoint() -> None:
    """The check command can render its help output."""
    completed = _run_python(
        "-c",
        "import sys; from orion_decision.cli import check; "
        "sys.argv = ['orion-check', '--help']; check()",
    )
    assert completed.returncode == 0, completed.stderr
    assert "Orion repo root" in completed.stdout


@pytest.mark.parametrize(
    "module",
    [
        "orion_decision.gha_plan",
        "orion_decision.gha_publish",
        "orion_decision.gha_run",
        "orion_decision.gha_workflows",
    ],
)
def test_workflow_module_help_entrypoints(module: str) -> None:
    """Workflow modules expose working help commands."""
    completed = _run_python("-m", module, "--help")
    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout.lower()
