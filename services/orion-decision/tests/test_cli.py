# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Tests for Orion decision CLI"""

from json import dumps as json_dump
from logging import DEBUG
from pathlib import Path
from unittest.mock import call

import pytest

from orion_decision.cli import (
    CISecretEnv,
    check,
    ci_check,
    ci_launch,
    ci_main,
    configure_logging,
    main,
    parse_args,
    parse_check_args,
    parse_ci_args,
    parse_ci_check_args,
    parse_ci_launch_args,
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


def test_ci_args(mocker):
    """test CI decision argument parsing"""
    mocker.patch("orion_decision.cli.getenv", autospec=True, return_value=None)
    test_matrix = {
        "language": "python",
    }
    with pytest.raises(SystemExit):
        parse_ci_args([])
    with pytest.raises(SystemExit):
        parse_ci_args(["--github-action", "github-push", "--github-event", "{blah}"])
    with pytest.raises(SystemExit):
        parse_ci_args(
            [
                "--github-action",
                "github-push",
                "--github-event",
                "{blah}",
                "--matrix",
                json_dump(test_matrix),
            ]
        )
    with pytest.raises(SystemExit):
        parse_ci_args(["--matrix", json_dump(test_matrix)])
    with pytest.raises(SystemExit):
        parse_ci_args(["--matrix", json_dump(test_matrix), "--project-name", "Orion"])
    result = parse_ci_args(
        [
            "--github-action",
            "github-push",
            "--github-event",
            "{blah}",
            "--matrix",
            json_dump(test_matrix),
            "--project-name",
            "Orion",
        ]
    )
    assert result.matrix == test_matrix
    assert result.project_name == "Orion"


def test_ci_check_args():
    """test CI check argument parsing"""
    result = parse_ci_check_args(["123", "456"])
    assert result.changed == [Path("123"), Path("456")]


def test_ci_launch_args(mocker):
    """test CI launcher argument parsing"""
    mocker.patch("orion_decision.cli.getenv", autospec=True, return_value=None)
    test_job = {
        "name": "test-ci-launch",
        "language": "python",
        "version": "3.9",
        "platform": "linux",
        "env": {},
        "script": ["fash"],
        "stage": 1,
        "require_previous_stage_pass": False,
        "secrets": [],
    }
    with pytest.raises(SystemExit):
        parse_ci_launch_args([])
    with pytest.raises(SystemExit):
        parse_ci_launch_args(["--job", "{}"])
    with pytest.raises(SystemExit):
        parse_ci_launch_args(["--job", "{}", "--fetch-ref", "abc"])
    with pytest.raises(SystemExit):
        parse_ci_launch_args(
            ["--job", "{}", "--fetch-ref", "abc", "--fetch-rev", "123"]
        )
    result = parse_ci_launch_args(
        [
            "--job",
            json_dump(test_job),
            "--fetch-ref",
            "abc",
            "--fetch-rev",
            "123",
            "--clone-repo",
            "test.allizom.org",
        ]
    )
    for key, value in test_job.items():
        assert getattr(result.job, key) == value
    assert result.fetch_ref == "abc"
    assert result.fetch_rev == "123"
    assert result.clone_repo == "test.allizom.org"


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


def test_ci_main(mocker):
    """test CLI main entrypoint for CI decision"""
    log_init = mocker.patch("orion_decision.cli.configure_logging", autospec=True)
    parser = mocker.patch("orion_decision.cli.parse_ci_args", autospec=True)
    sched = mocker.patch("orion_decision.cli.CIScheduler", autospec=True)
    with pytest.raises(SystemExit) as exc:
        ci_main()
    assert log_init.call_count == 1
    assert parser.call_count == 1
    assert log_init.call_args == call(level=parser.return_value.log_level)
    assert sched.main.call_count == 1
    assert sched.main.call_args == call(parser.return_value)
    assert exc.value.code == sched.main.return_value


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


def test_ci_check(mocker):
    """test CLI entrypoint for CI check"""
    log_init = mocker.patch("orion_decision.cli.configure_logging", autospec=True)
    parser = mocker.patch("orion_decision.cli.parse_ci_check_args", autospec=True)
    checker = mocker.patch("orion_decision.cli.check_matrix", autospec=True)
    with pytest.raises(SystemExit) as exc:
        ci_check()
    assert log_init.call_count == 1
    assert parser.call_count == 1
    assert log_init.call_args == call(level=parser.return_value.log_level)
    assert checker.call_count == 1
    assert checker.call_args == call(parser.return_value)
    assert exc.value.code == 0


@pytest.mark.parametrize(
    "platform, secret",
    [
        (None, None),
        (None, "env"),
        (None, "other"),
        ("windows", None),
    ],
)
def test_ci_launch_01(mocker, platform, secret):
    """test CLI entrypoint for CI launch"""
    log_init = mocker.patch("orion_decision.cli.configure_logging", autospec=True)
    parser = mocker.patch("orion_decision.cli.parse_ci_launch_args", autospec=True)
    chdir = mocker.patch("orion_decision.cli.chdir", autospec=True)
    environ = mocker.patch("orion_decision.cli.os_environ", autospec=True)
    execvpe = mocker.patch("orion_decision.cli.execvpe", autospec=True)
    repo = mocker.patch("orion_decision.cli.GitRepo", autospec=True)
    mocker.patch.object(CISecretEnv, "get_secret_data", return_value="secret")
    copy = {}
    environ.copy.return_value = copy

    if platform == "windows":
        parser.return_value.job.platform = "windows"
        list2cmdline = mocker.patch("orion_decision.cli.list2cmdline", autospec=True)

    if secret == "env":
        sec = CISecretEnv("secret", "name")
        parser.return_value.job.secrets = [sec]

    elif secret == "other":
        sec = mocker.MagicMock()
        parser.return_value.job.secrets = [sec]

    ci_launch()

    assert log_init.call_count == 1
    assert parser.call_count == 1
    assert log_init.call_args == call(level=parser.return_value.log_level)
    assert chdir.call_count == 1
    assert repo.call_count == 1
    assert repo.call_args == call(
        parser.return_value.clone_repo,
        parser.return_value.fetch_ref,
        parser.return_value.fetch_rev,
    )
    assert chdir.call_args == call(repo.return_value.path)
    assert execvpe.call_count == 1
    cmd = parser.return_value.job.script

    # check that windows command is written
    if platform == "windows":
        assert list2cmdline.call_count == 1
        assert list2cmdline.call_args == call(cmd)
        assert execvpe.call_args == call(
            "bash", ["bash", "-c", list2cmdline.return_value, cmd[0]], copy
        )
    else:
        assert execvpe.call_args == call(cmd[0], cmd, environ.copy.return_value)

    # check that env secret is put in env
    if secret == "env":
        assert sec.get_secret_data.call_count == 1
        assert copy[sec.name] == sec.get_secret_data.return_value

    # check that non-env secret gets written
    elif secret == "other":
        assert not copy
        assert sec.write.call_count == 1


def test_ci_launch_02(mocker):
    """test CLI entrypoint for CI launch"""
    mocker.patch("orion_decision.cli.configure_logging", autospec=True)
    parser = mocker.patch("orion_decision.cli.parse_ci_launch_args", autospec=True)
    mocker.patch("orion_decision.cli.chdir", autospec=True)
    environ = mocker.patch("orion_decision.cli.os_environ", autospec=True)
    mocker.patch("orion_decision.cli.execvpe", autospec=True)
    mocker.patch("orion_decision.cli.GitRepo", autospec=True)
    mocker.patch.object(CISecretEnv, "get_secret_data", return_value={"key": "secret"})
    copy = {}
    environ.copy.return_value = copy

    sec = CISecretEnv("secret", "name")
    parser.return_value.job.secrets = [sec]

    with pytest.raises(AssertionError) as exc:
        ci_launch()

    assert "missing `key`" in str(exc)


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
