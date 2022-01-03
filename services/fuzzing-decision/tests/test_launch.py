# -*- coding: utf-8 -*-

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock, patch

from _pytest.monkeypatch import MonkeyPatch
import pytest
import yaml

from fuzzing_decision.common.pool import PoolConfigData
from fuzzing_decision.pool_launch import cli
from fuzzing_decision.pool_launch.launcher import PoolLauncher


@patch("fuzzing_decision.pool_launch.cli.PoolLauncher", autospec=True)
def test_main_calls(mock_launcher) -> None:
    # if configure returns None, clone/load_params should not be called
    mock_launcher.return_value.configure.return_value = None
    cli.main([])
    mock_launcher.assert_called_once()
    mock_launcher.return_value.configure.assert_called_once()
    mock_launcher.return_value.clone.assert_not_called()
    mock_launcher.return_value.load_params.assert_not_called()
    mock_launcher.return_value.exec.assert_called_once()

    # if configure returns something, clone/load_params should be called
    mock_launcher.reset_mock(return_value=True)
    mock_launcher.return_value = Mock(spec=PoolLauncher)
    mock_launcher.return_value.configure.return_value = {}
    cli.main([])
    mock_launcher.assert_called_once()
    mock_launcher.return_value.configure.assert_called_once()
    mock_launcher.return_value.clone.assert_called_once()
    mock_launcher.return_value.load_params.assert_called_once()
    mock_launcher.return_value.exec.assert_called_once()


@patch("os.environ", {})
def test_load_params(tmp_path: Path) -> None:
    os.environ["STATIC"] = "value"
    pool_data: PoolConfigData = {
        "cloud": "aws",
        "scopes": [],
        "disk_size": "120g",
        "cycle_time": "1h",
        "max_run_time": "1h",
        "schedule_start": None,
        "cores_per_task": 10,
        "metal": False,
        "name": "Amazing fuzzing pool",
        "tasks": 3,
        "command": [],
        "container": "MozillaSecurity/fuzzer:latest",
        "minimum_memory_per_core": "1g",
        "imageset": "generic-worker-A",
        "parents": [],
        "cpu": "arm64",
        "platform": "linux",
        "preprocess": "",
        "macros": {"ENVVAR1": "123456", "ENVVAR2": "789abc"},
        "run_as_admin": False,
    }

    # test 1: environment from pool is merged
    launcher = PoolLauncher(["command", "arg"], "test-pool")
    launcher.fuzzing_config_dir = tmp_path
    with (tmp_path / "test-pool.yml").open("w") as test_cfg:
        yaml.dump(pool_data, stream=test_cfg)

    launcher.load_params()
    assert launcher.command == ["command", "arg"]
    assert launcher.environment == {
        "ENVVAR1": "123456",
        "ENVVAR2": "789abc",
        "STATIC": "value",
    }

    # test 2: command from pool is used
    pool_data["macros"].clear()
    pool_data["command"] = ["new-command", "arg1", "arg2"]
    launcher = PoolLauncher([], "test-pool")
    launcher.fuzzing_config_dir = tmp_path
    with (tmp_path / "test-pool.yml").open("w") as test_cfg:
        yaml.dump(pool_data, stream=test_cfg)

    launcher.load_params()
    assert launcher.command == ["new-command", "arg1", "arg2"]
    assert launcher.environment == {"STATIC": "value"}

    # test 3: command from init and pool is error
    launcher = PoolLauncher(["command", "arg"], "test-pool")
    launcher.fuzzing_config_dir = tmp_path

    with pytest.raises(AssertionError):
        launcher.load_params()

    # test 4: preprocess task is loaded
    preproc_data: PoolConfigData = {
        "cloud": None,
        "scopes": [],
        "disk_size": None,
        "cycle_time": None,
        "max_run_time": None,
        "schedule_start": None,
        "cores_per_task": None,
        "metal": None,
        "name": "preproc",
        "tasks": 1,
        "command": None,
        "container": None,
        "minimum_memory_per_core": None,
        "imageset": None,
        "parents": [],
        "cpu": None,
        "platform": None,
        "preprocess": None,
        "macros": {"PREPROC": "1"},
        "run_as_admin": False,
    }
    pool_data["preprocess"] = "preproc"
    with (tmp_path / "test-pool.yml").open("w") as test_cfg:
        yaml.dump(pool_data, stream=test_cfg)
    with (tmp_path / "preproc.yml").open("w") as test_cfg:
        yaml.dump(preproc_data, stream=test_cfg)

    launcher = PoolLauncher([], "test-pool", True)
    launcher.fuzzing_config_dir = tmp_path

    launcher.load_params()
    assert launcher.command == ["new-command", "arg1", "arg2"]
    assert launcher.environment == {"STATIC": "value", "PREPROC": "1"}


def test_launch_exec(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    # Start with taskcluster detection disabled, even on CI
    monkeypatch.delenv("TASK_ID", raising=False)
    monkeypatch.delenv("TASKCLUSTER_ROOT_URL", raising=False)
    with patch("os.execvpe"), patch("os.dup2"):
        pool = PoolLauncher(["cmd"], "testpool")
        assert pool.in_taskcluster is False
        pool.log_dir = tmp_path / "logs"
        pool.exec()
        os.dup2.assert_not_called()
        os.execvpe.assert_called_once_with("cmd", ["cmd"], pool.environment)
        assert not pool.log_dir.is_dir()

        # Then enable taskcluster detection
        monkeypatch.setenv("TASK_ID", "someTask")
        monkeypatch.setenv("TASKCLUSTER_ROOT_URL", "http://fakeTaskcluster")
        assert pool.in_taskcluster is True

        os.execvpe.reset_mock()
        pool.exec()
        assert os.dup2.call_count == 2
        os.execvpe.assert_called_once_with("cmd", ["cmd"], pool.environment)
        assert pool.log_dir.is_dir()
