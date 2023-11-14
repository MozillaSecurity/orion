# type: ignore
# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import os
from typing import Any, Dict
from unittest.mock import Mock, patch

import pytest
import yaml

from fuzzing_decision.pool_launch import cli
from fuzzing_decision.pool_launch.launcher import PoolLauncher


@patch("fuzzing_decision.pool_launch.cli.PoolLauncher", autospec=True)
def test_main_calls(mock_launcher):
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
    mock_launcher.return_value.configure.return_value = {
        "fuzzing_config": {"path": None}
    }
    cli.main([])
    mock_launcher.assert_called_once()
    mock_launcher.return_value.configure.assert_called_once()
    mock_launcher.return_value.clone.assert_called_once()
    mock_launcher.return_value.load_params.assert_called_once()
    mock_launcher.return_value.exec.assert_called_once()


@pytest.fixture
def pool_data():
    return {
        "cloud": "aws",
        "scopes": [],
        "disk_size": "120g",
        "cycle_time": "1h",
        "max_run_time": "1h",
        "schedule_start": None,
        "cores_per_task": 10,
        "demand": False,
        "gpu": False,
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
        "macros": {},
        "run_as_admin": False,
        "nested_virtualization": False,
    }


@patch("os.environ", {})
def test_load_params_1(tmp_path, pool_data):
    os.environ["STATIC"] = "value"
    pool_data["macros"]["ENVVAR1"] = "123456"
    pool_data["macros"]["ENVVAR2"] = "789abc"
    pool_data["macros"]["ENVVAR3"] = "failed!"

    # test 1: environment from pool is merged
    launcher = PoolLauncher(["command", "arg"], "test-pool")
    launcher.environment["ENVVAR3"] = "NO_MOD"
    launcher.fuzzing_config_dir = tmp_path
    with (tmp_path / "test-pool.yml").open("w") as test_cfg:
        yaml.dump(pool_data, stream=test_cfg)

    launcher.load_params()
    assert launcher.command == ["command", "arg"]
    assert launcher.environment == {
        "ENVVAR1": "123456",
        "ENVVAR2": "789abc",
        "ENVVAR3": "NO_MOD",
        "FUZZING_POOL_NAME": "Amazing fuzzing pool",
        "STATIC": "value",
    }


@patch("os.environ", {})
def test_load_params_2(tmp_path, pool_data):
    os.environ["STATIC"] = "value"
    pool_data["command"] = ["new-command", "arg1", "arg2"]

    # test 2: command from pool is used
    launcher = PoolLauncher([], "test-pool")
    launcher.fuzzing_config_dir = tmp_path
    with (tmp_path / "test-pool.yml").open("w") as test_cfg:
        yaml.dump(pool_data, stream=test_cfg)

    launcher.load_params()
    assert launcher.command == ["new-command", "arg1", "arg2"]
    assert launcher.environment == {
        "FUZZING_POOL_NAME": "Amazing fuzzing pool",
        "STATIC": "value",
    }


@patch("os.environ", {})
def test_load_params_3(tmp_path, pool_data):
    pool_data["command"] = ["new-command", "arg1", "arg2"]

    # test 3: command from init and pool is error
    launcher = PoolLauncher(["command", "arg"], "test-pool")
    launcher.fuzzing_config_dir = tmp_path
    with (tmp_path / "test-pool.yml").open("w") as test_cfg:
        yaml.dump(pool_data, stream=test_cfg)

    with pytest.raises(AssertionError):
        launcher.load_params()


@patch("os.environ", {})
def test_load_params_4(tmp_path, pool_data):
    os.environ["STATIC"] = "value"
    pool_data["command"] = ["new-command", "arg1", "arg2"]
    pool_data["preprocess"] = "preproc"

    # test 4: preprocess task is loaded
    preproc_data: Dict[str, Any] = {
        "cloud": None,
        "scopes": [],
        "disk_size": None,
        "cycle_time": None,
        "max_run_time": None,
        "schedule_start": None,
        "cores_per_task": None,
        "demand": None,
        "gpu": None,
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
    with (tmp_path / "test-pool.yml").open("w") as test_cfg:
        yaml.dump(pool_data, stream=test_cfg)
    with (tmp_path / "preproc.yml").open("w") as test_cfg:
        yaml.dump(preproc_data, stream=test_cfg)

    launcher = PoolLauncher([], "test-pool", True)
    launcher.fuzzing_config_dir = tmp_path

    launcher.load_params()
    assert launcher.command == ["new-command", "arg1", "arg2"]
    assert launcher.environment == {
        "FUZZING_POOL_NAME": "Amazing fuzzing pool (preproc)",
        "PREPROC": "1",
        "STATIC": "value",
    }


def test_launch_exec(tmp_path, monkeypatch, mocker):
    # Start with taskcluster detection disabled, even on CI
    monkeypatch.delenv("TASK_ID", raising=False)
    monkeypatch.delenv("TASKCLUSTER_ROOT_URL", raising=False)
    exec_mock = mocker.patch("os.execvpe")
    dup2_mock = mocker.patch("os.dup2")

    pool = PoolLauncher(["cmd"], "testpool")
    assert pool.in_taskcluster is False
    pool.log_dir = tmp_path / "logs"
    pool.exec()
    dup2_mock.assert_not_called()
    exec_mock.assert_called_once_with("cmd", ["cmd"], pool.environment)
    assert not pool.log_dir.is_dir()

    # Then enable taskcluster detection
    monkeypatch.setenv("TASK_ID", "someTask")
    monkeypatch.setenv("TASKCLUSTER_ROOT_URL", "http://fakeTaskcluster")
    assert pool.in_taskcluster is True

    exec_mock.reset_mock()
    pool.exec()
    assert dup2_mock.call_count == 2
    exec_mock.assert_called_once_with("cmd", ["cmd"], pool.environment)
    assert pool.log_dir.is_dir()
