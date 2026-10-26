# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Exercise worker lifetime independently of publication producer failures."""

from __future__ import annotations

import signal
import urllib.error
from email.message import Message
from types import SimpleNamespace

import pytest

from orion_decision import gha_pool


@pytest.fixture
def pool_plan(monkeypatch):
    """Describe one eligible publication and its automatic GitHub identity."""
    for key, value in {
        "GITHUB_REPOSITORY": "MozillaSecurity/orion",
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_RUN_NUMBER": "8",
        "GITHUB_TOKEN": "automatic-job-token",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        gha_pool,
        "_attempt_jobs",
        lambda *_args, **_kwargs: [
            {"name": f"Taskcluster worker {number}", "status": "in_progress"}
            for number in (1, 2)
        ],
    )
    return {"publish": True, "event": "push", "branch": "master", "revision": "a" * 40}


def _task(task_id, state, *, attempt="2"):
    return {
        "task": {"extra": {"orion": {"runId": "123", "runAttempt": attempt}}},
        "status": {"taskId": task_id, "state": state},
    }


def _artifacts(monkeypatch, plan, *, control=True):
    records = [
        {
            "id": 1,
            "name": "orion-publication-group-123-2",
            "digest": "sha256:" + "a" * 64,
        }
    ]
    if control:
        records.append(
            {
                "id": 2,
                "name": "orion-publication-control-123-2",
                "digest": "sha256:" + "b" * 64,
            }
        )
    monkeypatch.setattr(gha_pool, "_token", lambda: "worker-job-token")
    monkeypatch.setattr(gha_pool, "_actions_artifacts", lambda *_args: records)
    monkeypatch.setattr(
        gha_pool,
        "download_artifact_json",
        lambda *_args, **_kwargs: {**gha_pool.identity(plan), "task_group": "g" * 22},
    )
    monkeypatch.setattr(gha_pool.time, "sleep", lambda _seconds: None)


def test_empty_queue_does_not_stop_pool_before_submissions_close(
    pool_plan, monkeypatch
):
    """Long build gaps keep workers alive even before the first import exists."""
    _artifacts(monkeypatch, pool_plan)
    producer_polls = 0
    group_polls = 0

    def jobs(*_args):
        nonlocal producer_polls
        producer_polls += 1
        return [
            {
                "name": gha_pool.CLOSE_JOB,
                "status": "completed" if producer_polls == 3 else "in_progress",
            }
        ]

    class Queue:
        def listTaskGroup(self, group, **_kwargs):
            nonlocal group_polls
            group_polls += 1
            assert producer_polls == 3
            assert group == "g" * 22
            return {"tasks": []}

    monkeypatch.setattr(gha_pool, "_attempt_jobs", jobs)

    gha_pool.monitor_pool(pool_plan, queue=Queue(), poll_interval=0)

    assert producer_polls == 3
    assert group_polls == 1


def test_failed_import_does_not_stop_successful_peer(pool_plan, monkeypatch):
    """Drain every scheduled import before reporting a failure in one branch."""
    _artifacts(monkeypatch, pool_plan)
    monkeypatch.setattr(
        gha_pool,
        "_attempt_jobs",
        lambda *_args: [{"name": gha_pool.CLOSE_JOB, "status": "completed"}],
    )
    polls = 0

    class Queue:
        def listTaskGroup(self, _group, **_kwargs):
            nonlocal polls
            polls += 1
            return {
                "tasks": [
                    _task("broken", "failed"),
                    _task("healthy", "pending" if polls == 1 else "completed"),
                ]
            }

    with pytest.raises(RuntimeError, match="broken"):
        gha_pool.monitor_pool(pool_plan, queue=Queue(), poll_interval=0)

    assert polls == 2


def test_missing_control_still_drains_real_submissions(pool_plan, monkeypatch):
    """A failed final upload cannot orphan imports created by earlier producers."""
    _artifacts(monkeypatch, pool_plan, control=False)
    monkeypatch.setattr(
        gha_pool,
        "_attempt_jobs",
        lambda *_args: [{"name": gha_pool.CLOSE_JOB, "status": "completed"}],
    )
    polls = 0

    class Queue:
        def listTaskGroup(self, _group, **_kwargs):
            nonlocal polls
            polls += 1
            return {
                "tasks": [
                    _task(
                        "submitted-before-step-failed",
                        "running" if polls == 1 else "completed",
                    )
                ]
            }

    with pytest.raises(RuntimeError, match="control artifact is missing"):
        gha_pool.monitor_pool(pool_plan, queue=Queue(), poll_interval=0)

    assert polls == 2


def test_group_pagination_excludes_failed_previous_attempt():
    """Retrying a workflow shares its group without inheriting old failures."""

    class Queue:
        def listTaskGroup(self, _group, *, query):
            if not query:
                return {
                    "tasks": [_task("old", "failed", attempt="1")],
                    "continuationToken": "next",
                }
            assert query == {"continuationToken": "next"}
            return {"tasks": [_task("current", "completed")]}

    tasks = gha_pool.group_tasks("g" * 22, "123", "2", Queue())

    assert [item["status"]["taskId"] for item in tasks] == ["current"]


def test_monitor_failure_drains_worker_claiming_another_runs_task(
    pool_plan, monkeypatch
):
    """Ordinary monitor errors stop new claims without terminating active work."""
    signals = []
    worker = SimpleNamespace(
        poll=lambda: None,
        send_signal=signals.append,
        wait=lambda **_kwargs: 0,
    )
    monkeypatch.setattr(gha_pool.subprocess, "Popen", lambda *_args: worker)

    def failed_monitor(*_args, **_kwargs):
        raise RuntimeError("own import failed")

    monkeypatch.setattr(gha_pool, "monitor_pool", failed_monitor)

    with pytest.raises(RuntimeError, match="own import failed"):
        gha_pool.run_worker_pool(pool_plan, 10)

    assert signals == [signal.SIGUSR1]


def test_push_bootstrap_uses_actual_webhook_decision_group(pool_plan, monkeypatch):
    """All branch publishers reuse the real push root instead of synthetic groups."""
    root = "r" * 22
    index = SimpleNamespace(findTask=lambda route: {"taskId": root})
    queue = SimpleNamespace(
        task=lambda _task_id: {
            "extra": {
                "index": {
                    "data": {
                        "repository": "MozillaSecurity/orion",
                        "revision": pool_plan["revision"],
                        "root": True,
                    }
                }
            }
        }
    )
    monkeypatch.setattr(
        gha_pool.Taskcluster,
        "get_service",
        lambda name: {
            "index": index,
            "queue": queue,
        }[name],
    )

    assert gha_pool.bootstrap(pool_plan) == root


@pytest.mark.parametrize("problem", ["wrong-attempt", "wrong-group", "missing-task"])
def test_bad_control_drains_known_group_before_failing(pool_plan, monkeypatch, problem):
    """Invalid control metadata must not strand another active import."""
    _artifacts(monkeypatch, pool_plan)
    monkeypatch.setattr(
        gha_pool,
        "_attempt_jobs",
        lambda *_args: [{"name": gha_pool.CLOSE_JOB, "status": "completed"}],
    )

    def download(_artifact, filename, *_args, **_kwargs):
        record = {**gha_pool.identity(pool_plan), "task_group": "g" * 22}
        if filename == "publication-control.json":
            if problem == "wrong-attempt":
                record["runAttempt"] = "1"
            elif problem == "wrong-group":
                record["task_group"] = "b" * 22
            else:
                record["task_ids"] = ["m" * 22]
        return record

    class Missing(Exception):
        status_code = 404

    polls = 0

    class Queue:
        def listTaskGroup(self, group, **_kwargs):
            nonlocal polls
            polls += 1
            assert group == "g" * 22
            return {
                "tasks": [_task("healthy", "running" if polls == 1 else "completed")]
            }

        def status(self, _task_id):
            raise Missing()

    monkeypatch.setattr(gha_pool, "download_artifact_json", download)
    with pytest.raises(RuntimeError):
        gha_pool.monitor_pool(pool_plan, queue=Queue(), poll_interval=0)
    assert polls == 2


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError("https://api.github.com", 502, "busy", Message(), None),
        TimeoutError("socket read timed out"),
    ],
)
def test_github_outage_does_not_retire_worker_pool(pool_plan, monkeypatch, error):
    """Workers continue serving through temporary GitHub producer-status outages."""
    _artifacts(monkeypatch, pool_plan)
    polls = 0

    def jobs(*_args):
        nonlocal polls
        polls += 1
        if polls == 1:
            raise error
        return [
            {
                "name": gha_pool.CLOSE_JOB,
                "status": "in_progress" if polls == 2 else "completed",
            }
        ]

    monkeypatch.setattr(gha_pool, "_attempt_jobs", jobs)
    queue = SimpleNamespace(listTaskGroup=lambda *_args, **_kwargs: {"tasks": []})
    gha_pool.monitor_pool(pool_plan, queue=queue, poll_interval=0)
    assert polls == 3


@pytest.mark.parametrize(
    "states, allowed",
    [
        ([], False),
        (["in_progress"], False),
        (["completed", "completed"], False),
        (["completed", "in_progress"], True),
        (["queued", "queued"], True),
    ],
)
def test_submissions_require_this_attempts_worker_pool(
    pool_plan,
    monkeypatch,
    states,
    allowed,
):
    """Partial retries cannot submit orphan tasks; one failed member allows peers."""
    requests = []

    def jobs(repository, run_id, attempt, *, token):
        requests.append((repository, run_id, attempt, token))
        return [
            {"name": f"Taskcluster worker {number}", "status": state}
            for number, state in enumerate(states, 1)
        ]

    monkeypatch.setattr(gha_pool, "_attempt_jobs", jobs)
    if allowed:
        gha_pool.require_workers()
    else:
        with pytest.raises(RuntimeError, match="re-run all jobs"):
            gha_pool.require_workers()
    assert requests == [("MozillaSecurity/orion", "123", "2", "automatic-job-token")]
