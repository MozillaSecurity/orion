# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Tests for reduction strategy configuration and worker environments."""

from unittest.mock import Mock

import pytest

from grizzly_reduce_monitor import monitor

EXPECTED_DEFAULTS = (
    "list",
    "lines",
    "markup-tree-sitter",
    "css-merge",
    "css-tree-sitter",
    "js-control-flow",
    "js-remove-wrappers",
    "js-inline-functions",
    "js-proxy-inline",
    "js-object-properties",
    "js-unused-vars",
    "lines",
    "jschars",
    "prettier",
    "lines",
)


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Capture queued tasks without accessing Taskcluster or FuzzManager."""
    monkeypatch.delenv("REDUCE_STRATEGY", raising=False)
    monkeypatch.setenv("TASK_ID", "monitor-task")
    monkeypatch.setitem(monitor.TC_QUEUES, "macosx", "grizzly-reduce-worker-macos")
    result = Mock()
    result.findTask.return_value = {"taskId": "image-task"}
    monkeypatch.setattr(monitor.Taskcluster, "get_service", lambda service: result)
    monkeypatch.setattr(monitor, "CrashManager", Mock())
    return result


def make_crash(os_name: str) -> monitor.ReducibleCrash:
    """Create a crash for a worker platform."""
    return monitor.ReducibleCrash(
        id=123,
        bucket=None,
        tool="test",
        description="test crash",
        os=os_name,
        quality=5,
        has_gpu=False,
    )


@pytest.mark.parametrize("os_name", ["linux", "android", "windows", "macosx"])
def test_default_strategies(queue: Mock, os_name: str) -> None:
    """Each worker receives the requested order, including both lines passes."""
    instance = monitor.ReductionMonitor(tool_list=["test"])
    instance.queue_reduction_task(os_name, make_crash(os_name), None)
    task = queue.createTask.call_args.args[1]
    assert task["payload"]["env"]["REDUCE_STRATEGY"] == " ".join(EXPECTED_DEFAULTS)


@pytest.mark.parametrize("os_name", ["linux", "android", "windows", "macosx"])
def test_environment_override(
    queue: Mock, monkeypatch: pytest.MonkeyPatch, os_name: str
) -> None:
    """Monitor environment overrides propagate without losing duplicate passes."""
    monkeypatch.setenv("REDUCE_STRATEGY", "\tlines js-unused-vars\nlines ")
    instance = monitor.ReductionMonitor(tool_list=["test"])
    instance.queue_reduction_task(os_name, make_crash(os_name), None)
    task = queue.createTask.call_args.args[1]
    assert task["payload"]["env"]["REDUCE_STRATEGY"] == "lines js-unused-vars lines"


@pytest.mark.parametrize("strategies", [["css-tree-sitter"], []])
def test_explicit_override(
    queue: Mock, monkeypatch: pytest.MonkeyPatch, strategies: list[str]
) -> None:
    """Per-task strategies take precedence, including an explicit empty list."""
    monkeypatch.setenv("REDUCE_STRATEGY", "lines prettier")
    instance = monitor.ReductionMonitor(tool_list=["test"])
    instance.queue_reduction_task("linux", make_crash("linux"), None, strategies)
    env = queue.createTask.call_args.args[1]["payload"]["env"]
    if strategies:
        assert env["REDUCE_STRATEGY"] == "css-tree-sitter"
    else:
        assert "REDUCE_STRATEGY" not in env


@pytest.mark.parametrize("value", ["", " \t\n"])
def test_empty_environment(
    queue: Mock, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """An empty environment override leaves strategy selection to Grizzly."""
    monkeypatch.setenv("REDUCE_STRATEGY", value)
    instance = monitor.ReductionMonitor(tool_list=["test"])
    instance.queue_reduction_task("linux", make_crash("linux"), None)
    assert "REDUCE_STRATEGY" not in queue.createTask.call_args.args[1]["payload"]["env"]


def test_dry_run(queue: Mock) -> None:
    """Configuring strategies does not bypass dry-run behavior."""
    instance = monitor.ReductionMonitor(dry_run=True, tool_list=["test"])
    instance.queue_reduction_task("linux", make_crash("linux"), None)
    queue.createTask.assert_not_called()
