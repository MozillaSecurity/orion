# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Tests for Orion decision CLI"""

from unittest.mock import call

from orion_decision.cli import configure_logging, main, parse_args

import pytest


def test_args(mocker):
    """test decision argument parsing"""
    mocker.patch("orion_decision.cli.getenv", autospec=True, return_value=None)
    with pytest.raises(SystemExit):
        parse_args([])
    with pytest.raises(SystemExit):
        parse_args(["--github-action", "github-push", "--github-event", "{}"])
    parse_args(["--github-action", "github-push", "--github-event", "{blah}"])


def test_logging_init(mocker):
    """test logging initializer"""
    locale = mocker.patch("orion_decision.cli.setlocale", autospec=True)
    log_init = mocker.patch("orion_decision.cli.basicConfig", autospec=True)
    level = mocker.Mock()
    configure_logging(level)
    assert locale.call_count == 1
    assert log_init.call_count == 1
    assert log_init.call_args == call(level=level)


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
