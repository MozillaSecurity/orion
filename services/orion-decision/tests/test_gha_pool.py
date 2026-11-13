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
from taskcluster.exceptions import TaskclusterFailure

from orion_decision import gha_pool
from orion_decision.gha_plan import job_id


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
    return {"publish": True, "event": "push", "branch": "main", "revision": "a" * 40}


def _task(task_id, state, *, attempt="2"):
    return {
        "task": {"extra": {"orion": {"runId": "123", "runAttempt": attempt}}},
        "status": {"taskId": task_id, "state": state},
    }


def test_group_publication_mapping_finds_actual_prior_attempt_tasks(pool_plan):
    """Resolve inherited import and receipt submissions by their stored identity."""
    group = gha_pool.artifact_task_id("123", 1, "decision")
    data = {
        "runId": "123",
        "revision": "a" * 40,
        "repository": "MozillaSecurity/orion",
    }
    import_id = gha_pool.artifact_task_id("123", 2, "langfuzz-amd64")
    receipt_id = gha_pool.artifact_task_id("123", 1, "receipt-langfuzz")
    records = [
        {
            "task": {
                "taskGroupId": group,
                "extra": {
                    "orion": {
                        **data,
                        "runAttempt": "2",
                        "artifactKey": "langfuzz-amd64",
                        "publicationKind": "import",
                    }
                },
            },
            "status": {"taskId": import_id, "state": "running"},
        },
        {
            "task": {
                "taskGroupId": group,
                "extra": {
                    "orion": {
                        **data,
                        "runAttempt": "1",
                        "service": "langfuzz",
                    }
                },
            },
            "status": {"taskId": receipt_id, "state": "completed"},
        },
        {
            "task": {
                "taskGroupId": group,
                "extra": {
                    "orion": {
                        **data,
                        "runAttempt": "4",
                        "artifactKey": "langfuzz-arm64",
                        "publicationKind": "import",
                    }
                },
            },
            "status": {"taskId": gha_pool.artifact_task_id("123", 4, "langfuzz-arm64")},
        },
    ]

    class Queue:
        def listTaskGroup(self, _group, query=None):
            if query:
                return {"tasks": []}
            return {"tasks": records}

    mapping = gha_pool._group_publication_tasks(group, data, "3", Queue())

    assert mapping[("import", "langfuzz-amd64")] == (2, import_id)
    assert mapping[("receipt", "langfuzz")] == (1, receipt_id)
    assert ("import", "langfuzz-arm64") not in mapping


def test_receipt_depends_on_actual_inherited_imports(pool_plan, monkeypatch):
    """Schedule a current receipt against imports inherited from an earlier attempt."""
    from orion_decision import orion

    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "3")
    group = gha_pool.artifact_task_id("123", 1, "decision")
    plan = {
        "publish": True,
        "branch": "main",
        "event": "push",
        "revision": "a" * 40,
        "selected_jobs": [
            job_id("build", "fuzzilli", "amd64"),
            job_id("build", "fuzzilli", "arm64"),
        ],
    }
    imports = []
    for arch in ("amd64", "arm64"):
        key = f"fuzzilli-{arch}"
        imports.append(
            {
                "task": {
                    "taskGroupId": group,
                    "extra": {
                        "orion": {
                            "runId": "123",
                            "runAttempt": "2",
                            "revision": "a" * 40,
                            "repository": "MozillaSecurity/orion",
                            "artifactKey": key,
                            "publicationKind": "import",
                        }
                    },
                },
                "status": {
                    "taskId": gha_pool.artifact_task_id("123", 2, key),
                    "state": "running",
                },
            }
        )

    class FakeQueue:
        def listTaskGroup(self, _group, query=None):
            return {"tasks": imports}

    queue = FakeQueue()
    monkeypatch.setattr(gha_pool.Taskcluster, "get_service", lambda _name: queue)
    monkeypatch.setattr(gha_pool, "require_workers", lambda: None)
    monkeypatch.setattr(
        gha_pool,
        "_actions_artifacts",
        lambda *_args: [
            {
                "id": 22,
                "name": "orion-published-image-digests-fuzzilli-123-1",
                "digest": "sha256:" + "a" * 64,
            }
        ],
    )
    downloaded_artifacts = []

    def download_artifact(artifact_id, *_args, **_kwargs):
        downloaded_artifacts.append(artifact_id)
        return {
            "fuzzilli": {
                "latest_published": True,
                "architectures": {
                    "amd64": "sha256:" + "b" * 64,
                    "arm64": "sha256:" + "c" * 64,
                },
            }
        }

    monkeypatch.setattr(
        gha_pool,
        "download_artifact_json",
        download_artifact,
    )
    submitted = {}
    monkeypatch.setattr(gha_pool, "submit_tasks", lambda tasks: submitted.update(tasks))

    class FakeService:
        name = "fuzzilli"
        archs = ("amd64", "arm64")

    class TestOnly:
        pass

    monkeypatch.setattr(orion, "Services", lambda _repo: {"fuzzilli": FakeService()})
    monkeypatch.setattr(orion, "ServiceHomebrew", type("Homebrew", (), {}))
    monkeypatch.setattr(orion, "ServiceMsys", type("Msys", (), {}))
    monkeypatch.setattr(orion, "ServiceTestOnly", TestOnly)
    monkeypatch.setattr(
        "orion_decision.git.GitRepo.from_existing", lambda _path: object()
    )

    receipt_id = gha_pool.schedule_receipt(plan, "fuzzilli", group)
    receipt = submitted[receipt_id]

    assert receipt_id == gha_pool.artifact_task_id("123", 3, "receipt-fuzzilli")
    assert receipt["dependencies"] == [
        gha_pool.artifact_task_id("123", 2, "fuzzilli-amd64"),
        gha_pool.artifact_task_id("123", 2, "fuzzilli-arm64"),
    ]
    assert receipt["extra"]["orion"]["runAttempt"] == "3"
    assert (
        receipt["extra"]["orion"]["published_images"]["fuzzilli"]["latest_published"]
        is True
    )
    assert downloaded_artifacts == [22]
    assert receipt["extra"]["index"]["rank"] == 803


def test_close_submissions_records_inherited_task_ids(tmp_path, pool_plan, monkeypatch):
    """Keep inherited imports and receipts in the current monitor control record."""
    import json

    from orion_decision import orion

    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "3")
    group = gha_pool.artifact_task_id("123", 1, "decision")
    plan = {
        "publish": True,
        "branch": "main",
        "event": "push",
        "revision": "a" * 40,
        "selected_jobs": [
            job_id("build", "fuzzilli", "amd64"),
            job_id("build", "fuzzilli", "arm64"),
        ],
    }
    results = {
        name: {"result": "success"}
        for name in (
            "plan",
            "publication-bootstrap",
            "graph-result",
            job_id("index", "fuzzilli", "amd64"),
            job_id("index", "fuzzilli", "arm64"),
            job_id("receipt", "fuzzilli"),
        )
    }
    monkeypatch.setenv("ORION_JOB_RESULTS", json.dumps(results))
    imports = []
    for arch in ("amd64", "arm64"):
        key = f"fuzzilli-{arch}"
        imports.append(
            {
                "task": {
                    "taskGroupId": group,
                    "extra": {
                        "orion": {
                            "runId": "123",
                            "runAttempt": "2",
                            "revision": "a" * 40,
                            "repository": "MozillaSecurity/orion",
                            "artifactKey": key,
                            "publicationKind": "import",
                        }
                    },
                },
                "status": {
                    "taskId": gha_pool.artifact_task_id("123", 2, key),
                    "state": "running",
                },
            }
        )
    receipt_id = gha_pool.artifact_task_id("123", 1, "receipt-fuzzilli")
    imports.append(
        {
            "task": {
                "taskGroupId": group,
                "extra": {
                    "orion": {
                        "runId": "123",
                        "runAttempt": "1",
                        "revision": "a" * 40,
                        "repository": "MozillaSecurity/orion",
                        "service": "fuzzilli",
                    }
                },
            },
            "status": {"taskId": receipt_id, "state": "running"},
        }
    )

    class FakeQueue:
        def listTaskGroup(self, _group, query=None):
            return {"tasks": imports}

    monkeypatch.setattr(gha_pool.Taskcluster, "get_service", lambda _name: FakeQueue())
    monkeypatch.setattr(gha_pool, "require_workers", lambda: None)
    submitted = {}
    monkeypatch.setattr(gha_pool, "submit_tasks", lambda tasks: submitted.update(tasks))

    class FakeService:
        name = "fuzzilli"
        archs = ("amd64", "arm64")

    monkeypatch.setattr(orion, "Services", lambda _repo: {"fuzzilli": FakeService()})
    monkeypatch.setattr(orion, "ServiceTestOnly", type("TestOnly", (), {}))
    monkeypatch.setattr(
        "orion_decision.git.GitRepo.from_existing", lambda _path: object()
    )
    output = tmp_path / "control.json"

    gha_pool.close_submissions(plan, group, output)
    record = json.loads(output.read_text())
    marker = submitted[gha_pool.artifact_task_id("123", 3, "publication-marker")]

    assert set(record["task_ids"]) == {
        gha_pool.artifact_task_id("123", 2, "fuzzilli-amd64"),
        gha_pool.artifact_task_id("123", 2, "fuzzilli-arm64"),
        receipt_id,
        gha_pool.artifact_task_id("123", 3, "publication-marker"),
    }
    assert set(marker["dependencies"]) == {
        gha_pool.artifact_task_id("123", 2, "fuzzilli-amd64"),
        gha_pool.artifact_task_id("123", 2, "fuzzilli-arm64"),
        receipt_id,
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


@pytest.mark.parametrize(
    "conclusion, failed_jobs, message",
    [
        ("failure", [], "closed with conclusion failure"),
        ("success", ["index_funfuzz_amd64"], "Publication producers failed"),
    ],
)
def test_workers_drain_tasks_before_reporting_submission_failure(
    pool_plan, monkeypatch, conclusion, failed_jobs, message
):
    """Workers drain healthy tasks before reporting closure or producer failures."""
    _artifacts(monkeypatch, pool_plan)
    identity = gha_pool.identity(pool_plan)
    task_id = gha_pool.artifact_task_id("123", 2, "funfuzz-amd64")

    def download(_artifact, filename, *_args, **_kwargs):
        record = {**identity, "task_group": "g" * 22}
        if filename == "publication-control.json":
            record["failed_jobs"] = failed_jobs
            record["task_ids"] = [task_id]
        return record

    monkeypatch.setattr(gha_pool, "download_artifact_json", download)
    monkeypatch.setattr(
        gha_pool,
        "_attempt_jobs",
        lambda *_args: [
            {
                "name": gha_pool.CLOSE_JOB,
                "status": "completed",
                "conclusion": conclusion,
            }
        ],
    )
    polls = 0

    class Queue:
        def listTaskGroup(self, _group, **_kwargs):
            nonlocal polls
            polls += 1
            return {"tasks": [_task(task_id, "pending" if polls == 1 else "completed")]}

    with pytest.raises(RuntimeError, match=message):
        gha_pool.monitor_pool(pool_plan, queue=Queue(), poll_interval=0)

    assert polls == 2


def test_monitor_waits_for_inherited_task_ids_from_close_control(
    pool_plan, monkeypatch
):
    """Wait for a pending prior-attempt task listed in this attempt's control."""
    _artifacts(monkeypatch, pool_plan)
    task_id = gha_pool.artifact_task_id("123", 1, "langfuzz-amd64")
    identity = gha_pool.identity(pool_plan)

    def download(_artifact, filename, *_args, **_kwargs):
        record = {**identity, "task_group": "g" * 22}
        if filename == "publication-control.json":
            record.update({"failed_jobs": [], "task_ids": [task_id]})
        return record

    monkeypatch.setattr(gha_pool, "download_artifact_json", download)
    monkeypatch.setattr(
        gha_pool,
        "_attempt_jobs",
        lambda *_args: [{"name": gha_pool.CLOSE_JOB, "status": "completed"}],
    )
    polls = 0

    class Queue:
        def listTaskGroup(self, _group, **_kwargs):
            unrelated_failure = gha_pool.artifact_task_id("123", 1, "unrelated-import")
            return {
                "tasks": [
                    {
                        "task": {
                            "taskGroupId": "g" * 22,
                            "extra": {"orion": {"runId": "123", "runAttempt": "1"}},
                        },
                        "status": {
                            "taskId": unrelated_failure,
                            "state": "failed",
                        },
                    }
                ]
            }

        def status(self, requested):
            nonlocal polls
            assert requested == task_id
            polls += 1
            state = "pending" if polls == 1 else "completed"
            return {"status": {"taskId": task_id, "state": state}}

    gha_pool.monitor_pool(pool_plan, queue=Queue(), poll_interval=0)

    assert polls == 2


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


@pytest.mark.parametrize("event", ["push", "schedule", "workflow_dispatch"])
def test_bootstrap_submits_same_run_root_for_every_event(pool_plan, monkeypatch, event):
    """Every publication event creates its group directly under a stable run root."""
    submitted = {}
    monkeypatch.setattr(gha_pool, "submit_tasks", lambda tasks: submitted.update(tasks))
    monkeypatch.setattr(
        gha_pool.Taskcluster,
        "get_service",
        lambda name: pytest.fail(f"bootstrap must not call Taskcluster {name} API"),
    )
    plan = {**pool_plan, "event": event}

    root_id = gha_pool.bootstrap(plan)

    expected_id = gha_pool.artifact_task_id("123", 1, "decision")
    root = submitted[expected_id]
    assert root_id == expected_id
    assert root["taskGroupId"] == expected_id
    assert root["routes"] == [f"index.{gha_pool.GROUP_ROUTE}.run.123"]
    assert root["extra"]["orion"] == {
        "repository": "MozillaSecurity/orion",
        "revision": "a" * 40,
        "event": event,
        "branch": "main",
        "runId": "123",
        "runAttempt": "1",
        "runNumber": 8,
        "root": True,
    }


def test_bootstrap_reuses_retry_root_and_rejects_changed_provenance(
    pool_plan, monkeypatch
):
    """Stable root IDs make exact retries safe and reject a changed revision."""

    class AlreadyExists(TaskclusterFailure):
        status_code = 409

    class Queue:
        def __init__(self):
            self.tasks = {}

        def createTask(self, task_id, task):
            if task_id in self.tasks:
                raise AlreadyExists("duplicate")
            self.tasks[task_id] = task

        def task(self, task_id):
            return self.tasks[task_id]

    queue = Queue()
    monkeypatch.setattr(gha_pool.Taskcluster, "get_service", lambda _name: queue)
    first_id = gha_pool.bootstrap(pool_plan)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "3")
    retry_id = gha_pool.bootstrap(pool_plan)

    assert retry_id == first_id
    assert len(queue.tasks) == 1
    changed = {**pool_plan, "revision": "b" * 40}
    with pytest.raises(RuntimeError, match="different publication provenance"):
        gha_pool.bootstrap(changed)


@pytest.mark.parametrize("final_root_state", ["completed", "failed"])
def test_retry_waits_for_queued_shared_root_after_imports_complete(
    pool_plan, monkeypatch, final_root_state
):
    """A retry waits for its queued root but ignores a prior root's final result."""
    root_id = gha_pool.artifact_task_id("123", 1, "decision")
    _artifacts(monkeypatch, pool_plan)

    def download(_artifact, filename, *_args, **_kwargs):
        record = {**gha_pool.identity(pool_plan), "task_group": root_id}
        if filename == "publication-control.json":
            record["task_ids"] = []
        return record

    monkeypatch.setattr(gha_pool, "download_artifact_json", download)
    monkeypatch.setattr(
        gha_pool,
        "_attempt_jobs",
        lambda *_args: [{"name": gha_pool.CLOSE_JOB, "status": "completed"}],
    )
    calls = 0

    class Queue:
        def listTaskGroup(self, group, **_kwargs):
            nonlocal calls
            calls += 1
            assert group == root_id
            root_state = "pending" if calls == 1 else final_root_state
            return {
                "tasks": [
                    _task(root_id, root_state, attempt="1"),
                    _task("attempt-2-import", "completed"),
                ]
            }

    monkeypatch.setattr(
        gha_pool.Taskcluster,
        "get_service",
        lambda name: (_ for _ in ()).throw(AssertionError(name))
        if name == "index"
        else None,
    )
    gha_pool.monitor_pool(pool_plan, queue=Queue(), poll_interval=0)

    assert calls == 2


def test_missing_group_metadata_drains_deterministic_run_root(pool_plan, monkeypatch):
    """Missing Actions metadata still drains current submissions through the root."""
    monkeypatch.setattr(gha_pool, "_token", lambda: "worker-job-token")
    monkeypatch.setattr(gha_pool, "_actions_artifacts", lambda *_args: [])
    monkeypatch.setattr(
        gha_pool,
        "_attempt_jobs",
        lambda *_args: [{"name": gha_pool.CLOSE_JOB, "status": "completed"}],
    )
    root_id = gha_pool.artifact_task_id("123", 1, "decision")
    calls = 0

    class Queue:
        def listTaskGroup(self, group, **_kwargs):
            nonlocal calls
            calls += 1
            assert group == root_id
            state = "running" if calls == 1 else "completed"
            return {"tasks": [_task("attempt-2-import", state)]}

    monkeypatch.setattr(
        gha_pool.Taskcluster,
        "get_service",
        lambda name: pytest.fail(f"monitor must not call Taskcluster {name} API"),
    )
    with pytest.raises(RuntimeError, match="control artifact is missing"):
        gha_pool.monitor_pool(pool_plan, queue=Queue(), poll_interval=0)

    assert calls == 2


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


def test_attempt_jobs_uses_small_pages_and_collects_all_jobs(monkeypatch):
    """Fetch all attempt jobs in smaller GitHub pages that avoid large responses."""
    requests = []

    def github_json(url, *, token):
        requests.append((url, token))
        page = int(url.rsplit("page=", 1)[1])
        if page == 1:
            return {"jobs": [{"id": number} for number in range(20)]}
        return {"jobs": [{"id": 20}]}

    monkeypatch.setattr(gha_pool, "_github_json", github_json)

    jobs = gha_pool._attempt_jobs("MozillaSecurity/orion", "123", "2", token="t")

    assert [job["id"] for job in jobs] == list(range(21))
    assert requests == [
        (
            "https://api.github.com/repos/MozillaSecurity/orion/actions/runs/123"
            "/attempts/2/jobs?per_page=20&page=1",
            "t",
        ),
        (
            "https://api.github.com/repos/MozillaSecurity/orion/actions/runs/123"
            "/attempts/2/jobs?per_page=20&page=2",
            "t",
        ),
    ]


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError("https://api.github.com", 502, "busy", Message(), None),
        urllib.error.HTTPError("https://api.github.com", 503, "busy", Message(), None),
        urllib.error.HTTPError("https://api.github.com", 429, "busy", Message(), None),
        urllib.error.URLError("connection reset"),
        TimeoutError("socket read timed out"),
    ],
)
def test_worker_pool_check_retries_transient_github_errors(
    pool_plan, monkeypatch, error
):
    """Transient API failures during submission validation recover before failing."""
    calls = 0

    def jobs(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise error
        return [
            {"name": f"Taskcluster worker {number}", "status": "in_progress"}
            for number in (1, 2)
        ]

    monkeypatch.setattr(gha_pool, "_attempt_jobs", jobs)
    monkeypatch.setattr(gha_pool.time, "sleep", lambda _seconds: None)

    gha_pool.require_workers()

    assert calls == 2


@pytest.mark.parametrize(
    "header, value",
    [("Retry-After", "1"), ("X-RateLimit-Remaining", "0")],
)
def test_worker_pool_check_retries_rate_limited_forbidden_response(
    pool_plan, monkeypatch, header, value
):
    """A rate-limited GitHub 403 is temporary even though ordinary 403s are not."""
    calls = 0
    headers = Message()
    headers[header] = value

    def jobs(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(
                "https://api.github.com", 403, "rate limited", headers, None
            )
        return [
            {"name": f"Taskcluster worker {number}", "status": "in_progress"}
            for number in (1, 2)
        ]

    monkeypatch.setattr(gha_pool, "_attempt_jobs", jobs)
    monkeypatch.setattr(gha_pool.time, "sleep", lambda _seconds: None)

    gha_pool.require_workers()

    assert calls == 2


def test_worker_pool_check_bounds_transient_github_retries(pool_plan, monkeypatch):
    """Persistent GitHub errors eventually stop submission validation attempts."""
    now = 0
    calls = 0

    def monotonic():
        return now

    def sleep(seconds):
        nonlocal now
        now += seconds

    def jobs(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise urllib.error.HTTPError(
            "https://api.github.com", 502, "busy", Message(), None
        )

    monkeypatch.setattr(gha_pool, "_attempt_jobs", jobs)
    monkeypatch.setattr(gha_pool.time, "monotonic", monotonic)
    monkeypatch.setattr(gha_pool.time, "sleep", sleep)

    with pytest.raises(TimeoutError, match="GitHub API unavailable"):
        gha_pool.require_workers()

    assert calls == 5
    assert now == gha_pool.REQUIRE_WORKERS_RETRY_TIMEOUT


@pytest.mark.parametrize("status", [401, 403])
def test_worker_pool_check_does_not_retry_permanent_github_errors(
    pool_plan, monkeypatch, status
):
    """Authentication and other permanent API failures fail without waiting."""
    calls = 0

    def jobs(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise urllib.error.HTTPError(
            "https://api.github.com", status, "forbidden", Message(), None
        )

    monkeypatch.setattr(gha_pool, "_attempt_jobs", jobs)
    monkeypatch.setattr(
        gha_pool.time, "sleep", lambda _seconds: pytest.fail("unexpected retry wait")
    )

    with pytest.raises(urllib.error.HTTPError):
        gha_pool.require_workers()

    assert calls == 1
