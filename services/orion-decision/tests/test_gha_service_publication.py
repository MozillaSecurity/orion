# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Behavioral tests for independent GHA service publication handoffs."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from orion_decision import gha_pool, gha_publish
from orion_decision.gha_plan import job_id
from orion_decision.git import GitRepo


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(root: Path) -> Path:
    root.mkdir()
    _git(root, "init", "-b", "master")
    _git(root, "config", "user.name", "Orion tests")
    _git(root, "config", "user.email", "orion-tests@example.invalid")
    files = {
        "services/docker/service.yaml": "name: docker\narch: [amd64, arm64]\n",
        "services/docker/Dockerfile": "FROM alpine:3.20\n",
        "services/native/service.yaml": "name: native\ntype: msys\nbase: base.tar.xz\n",
        "services/native/setup.sh": "#!/bin/sh\nexit 0\n",
        "services/peer/service.yaml": "name: peer\narch: [amd64]\n",
        "services/peer/Dockerfile": "FROM alpine:3.20\n",
    }
    for name, contents in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "service publication graph")
    return root


class FakeQueue:
    """Capture real task submissions while standing in for Taskcluster Queue."""

    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}

    def createTask(self, task_id: str, task: dict[str, Any]) -> None:
        self.tasks[task_id] = task


def _environment(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "GITHUB_REPOSITORY": "MozillaSecurity/orion",
        "GITHUB_RUN_ID": "123456789",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_RUN_NUMBER": "418",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF_NAME": "master",
        "GITHUB_TOKEN": "test-token",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        gha_pool,
        "_attempt_jobs",
        lambda *_args, **_kwargs: [
            {"name": "Taskcluster worker 1", "status": "in_progress"},
            {"name": "Taskcluster worker 2", "status": "in_progress"},
        ],
    )


def _plan(revision: str, selected_jobs: list[str]) -> dict[str, Any]:
    return {
        "revision": revision,
        "publish": True,
        "branch": "master",
        "event": "push",
        "selected_jobs": selected_jobs,
    }


def _install_queue(monkeypatch: pytest.MonkeyPatch) -> FakeQueue:
    queue = FakeQueue()
    monkeypatch.setattr(
        gha_publish.Taskcluster,
        "get_service",
        lambda name: queue if name == "queue" else pytest.fail(name),
    )
    return queue


def test_artifact_manifest_imports_only_successful_service_arch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Import one successful architecture while a peer and other arch are pending."""
    repo = _repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    _environment(monkeypatch)
    revision = GitRepo.from_existing(repo).head()
    own_arch = job_id("build", "docker", "amd64")
    arm_arch = job_id("build", "docker", "arm64")
    peer_arch = job_id("build", "peer", "amd64")
    plan = _plan(revision, [own_arch, arm_arch, peer_arch])
    monkeypatch.setenv(
        "ORION_JOB_RESULTS",
        json.dumps(
            {
                own_arch: {"result": "success"},
                arm_arch: {"result": "pending"},
                peer_arch: {"result": "running"},
            }
        ),
    )
    monkeypatch.setattr(
        gha_publish,
        "_actions_artifacts",
        lambda *_args: [
            {
                "id": 901,
                "name": "orion-build-docker-amd64-2",
                "digest": "sha256:" + "a" * 64,
            }
        ],
    )
    queue = _install_queue(monkeypatch)

    manifest = gha_publish.create_manifest(
        plan,
        token="test-token",
        service_name="docker",
        arch="amd64",
        artifact_only=True,
    )
    task_ids = gha_publish.create_tasks(manifest, "canonical-group")

    expected = gha_publish.artifact_task_id("123456789", "2", "docker-amd64")
    assert manifest["complete"] is True
    assert manifest["successful_jobs"] == [own_arch]
    assert [item["service"] for item in manifest["artifacts"]] == ["docker"]
    assert task_ids == [expected]
    assert queue.tasks[expected]["taskGroupId"] == "canonical-group"


def test_docker_receipt_requires_full_success_and_uses_only_own_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Create a service receipt only after its full Docker manifest is published."""
    repo = _repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    _environment(monkeypatch)
    revision = GitRepo.from_existing(repo).head()
    selected = [job_id("build", "docker", arch) for arch in ("amd64", "arm64")]
    plan = _plan(revision, [*selected, job_id("build", "peer", "amd64")])
    digest_artifact_name = "orion-published-image-digests-docker-123456789-2"
    monkeypatch.setattr(
        gha_pool,
        "_actions_artifacts",
        lambda *_args: [
            {"id": 902, "name": digest_artifact_name, "digest": "sha256:" + "b" * 64}
        ],
    )
    digests = {
        "docker": {
            "architectures": {
                "amd64": "sha256:" + "1" * 64,
                "arm64": "sha256:" + "2" * 64,
            },
            "latest_published": True,
        }
    }
    monkeypatch.setattr(
        gha_pool,
        "download_artifact_json",
        lambda *_args, **_kwargs: digests,
    )
    queue = _install_queue(monkeypatch)
    group = gha_publish.artifact_task_id("123456789", "1", "decision")

    receipt = gha_pool.schedule_receipt(plan, "docker", group)

    task = queue.tasks[receipt]
    assert receipt == gha_publish.artifact_task_id("123456789", "2", "receipt-docker")
    assert task["taskGroupId"] == group
    assert task["dependencies"] == [
        gha_publish.artifact_task_id("123456789", "2", "docker-amd64"),
        gha_publish.artifact_task_id("123456789", "2", "docker-arm64"),
    ]
    assert task["extra"]["orion"]["published_images"] == digests


@pytest.mark.parametrize(
    "publication",
    [
        {
            "architectures": {
                "amd64": "sha256:" + "1" * 64,
                "arm64": "sha256:" + "2" * 64,
            },
            "latest_published": False,
        },
        {
            "architectures": {"amd64": "sha256:" + "1" * 64},
            "latest_published": True,
        },
    ],
)
def test_docker_receipt_rejects_failed_or_incomplete_latest_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    publication: dict[str, Any],
) -> None:
    """Refuse a receipt when latest failed or any configured architecture is absent."""
    repo = _repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    _environment(monkeypatch)
    revision = GitRepo.from_existing(repo).head()
    plan = _plan(
        revision,
        [job_id("build", "docker", arch) for arch in ("amd64", "arm64")],
    )
    monkeypatch.setattr(
        gha_pool,
        "_actions_artifacts",
        lambda *_args: [
            {
                "id": 903,
                "name": "orion-published-image-digests-docker-123456789-2",
                "digest": "sha256:" + "c" * 64,
            }
        ],
    )
    monkeypatch.setattr(
        gha_pool,
        "download_artifact_json",
        lambda *_args, **_kwargs: {"docker": publication},
    )
    queue = _install_queue(monkeypatch)

    with pytest.raises(ValueError, match="Docker publication incomplete"):
        gha_pool.schedule_receipt(
            plan,
            "docker",
            gha_publish.artifact_task_id("123456789", "1", "decision"),
        )

    assert queue.tasks == {}


def test_native_receipt_needs_no_github_docker_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Schedule a native service receipt without querying Docker digest artifacts."""
    repo = _repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    _environment(monkeypatch)
    revision = GitRepo.from_existing(repo).head()
    plan = _plan(revision, [job_id("build", "native", "amd64")])
    monkeypatch.setattr(
        gha_pool,
        "_actions_artifacts",
        lambda *_args: pytest.fail("native receipts do not query Docker metadata"),
    )
    queue = _install_queue(monkeypatch)

    receipt = gha_pool.schedule_receipt(
        plan, "native", gha_publish.artifact_task_id("123456789", "1", "decision")
    )

    assert queue.tasks[receipt]["dependencies"] == [
        gha_publish.artifact_task_id("123456789", "2", "native-amd64")
    ]
    assert queue.tasks[receipt]["extra"]["orion"]["published_images"] == {}


def test_failed_close_writes_control_artifact_without_global_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Persist the close record after producer failure without a success marker."""
    repo = _repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    _environment(monkeypatch)
    revision = GitRepo.from_existing(repo).head()
    plan = _plan(revision, [job_id("build", "docker", "amd64")])
    monkeypatch.setenv(
        "ORION_JOB_RESULTS",
        json.dumps(
            {
                "plan": {"result": "success"},
                "publication-bootstrap": {"result": "success"},
                "graph-result": {"result": "success"},
                job_id("build", "docker", "amd64"): {"result": "failure"},
            }
        ),
    )
    queue = _install_queue(monkeypatch)
    output = tmp_path / "control" / "close.json"

    with pytest.raises(RuntimeError, match="Publication producers failed"):
        gha_pool.close_submissions(plan, "canonical-group", output)

    control = json.loads(output.read_text())
    assert control["task_group"] == "canonical-group"
    assert queue.tasks == {}
    assert control["failed_jobs"]


def test_successful_close_marker_depends_only_on_submitted_service_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publish a marker after own receipts without waiting for peer services."""
    repo = _repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    _environment(monkeypatch)
    revision = GitRepo.from_existing(repo).head()
    docker_jobs = [job_id("build", "docker", arch) for arch in ("amd64", "arm64")]
    plan = _plan(revision, docker_jobs)
    results = {
        "plan": {"result": "success"},
        "publication-bootstrap": {"result": "success"},
        "graph-result": {"result": "success"},
        job_id("receipt", "docker"): {"result": "success"},
        **{name: {"result": "success"} for name in docker_jobs},
    }
    monkeypatch.setenv("ORION_JOB_RESULTS", json.dumps(results))
    queue = _install_queue(monkeypatch)
    output = tmp_path / "control" / "close.json"

    gha_pool.close_submissions(plan, "canonical-group", output)

    marker_id = gha_publish.artifact_task_id("123456789", "2", "publication-marker")
    assert marker_id in queue.tasks
    assert queue.tasks[marker_id]["taskGroupId"] == "canonical-group"
    assert queue.tasks[marker_id]["dependencies"] == [
        gha_publish.artifact_task_id("123456789", "2", "receipt-docker")
    ]
    assert json.loads(output.read_text())["failed_jobs"] == []
