# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Tests for Orion decision CLI"""

from logging import DEBUG
from pathlib import Path
from unittest.mock import call

import pytest

from orion_decision.cli import (
    check,
    configure_logging,
    main,
    parse_args,
    parse_check_args,
)


def test_args(mocker):
    """test decision argument parsing"""
    mocker.patch("orion_decision.cli.getenv", autospec=True, return_value=None)
    with pytest.raises(SystemExit):
        parse_args([])
    with pytest.raises(SystemExit):
        parse_args(["--github-action", "github-push", "--github-event", "{}"])
    parse_args(["--github-action", "github-push", "--github-event", "{blah}"])


def test_check_args():
    """test service check argument parsing"""
    with pytest.raises(SystemExit):
        parse_check_args([])
    result = parse_check_args(["path"])
    assert result.repo == Path("path")


def test_logging_init(mocker):
    """test logging initializer"""
    locale = mocker.patch("orion_decision.cli.setlocale", autospec=True)
    log_init = mocker.patch("orion_decision.cli.basicConfig", autospec=True)
    configure_logging(level=DEBUG)
    assert locale.call_count == 1
    assert log_init.call_count == 1
    assert log_init.call_args == call(
        format="[%(levelname).1s] %(message)s", level=DEBUG
    )


def test_main(mocker):
    """test CLI main entrypoint"""
    log_init = mocker.patch("orion_decision.cli.configure_logging", autospec=True)
    parser = mocker.patch("orion_decision.cli.parse_args", autospec=True)
    sched = mocker.patch("orion_decision.cli.Scheduler", autospec=True)
    with pytest.raises(SystemExit) as exc:
        main()
    assert log_init.call_count == 1
    assert parser.call_count == 1
    assert log_init.call_args == call(level=parser.return_value.log_level)
    assert sched.main.call_count == 1
    assert sched.main.call_args == call(parser.return_value)
    assert exc.value.code == sched.main.return_value


def test_check(mocker):
    """test CLI check entrypoint"""
    log_init = mocker.patch("orion_decision.cli.configure_logging", autospec=True)
    parser = mocker.patch("orion_decision.cli.parse_check_args", autospec=True)
    repo = mocker.patch("orion_decision.cli.GitRepo", autospec=True)
    svcs = mocker.patch("orion_decision.cli.Services", autospec=True)
    with pytest.raises(SystemExit) as exc:
        check()
    assert log_init.call_count == 1
    assert parser.call_count == 1
    assert log_init.call_args == call(level=parser.return_value.log_level)
    assert repo.from_existing.call_count == 1
    assert repo.from_existing.call_args == call(parser.return_value.repo)
    assert svcs.call_count == 1
    assert svcs.call_args == call(repo.from_existing.return_value)
    assert exc.value.code == 0
