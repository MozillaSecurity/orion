# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Contract tests for the GitHub Actions to Taskcluster publication handoff."""

from __future__ import annotations

import io
import json
import os
import re
import stat
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from jsone import render as jsone_render
from yaml import safe_load

from orion_decision import gha_publish
from orion_decision.gha_plan import build_plan, job_id
from orion_decision.gha_workflows import render_workflow
from orion_decision.git import GitRepo
from orion_decision.orion import Services


@pytest.fixture
def manifest() -> dict[str, Any]:
    return {
        "schema": 2,
        "repository": "MozillaSecurity/orion",
        "revision": "a" * 40,
        "run_id": "123456789",
        "run_attempt": "2",
        "run_number": "418",
        "event": "push",
        "branch": "master",
        "workflow": "orion.yml",
        "selected_jobs": ["build_fuzzilli_amd64", "build_fuzzilli_arm64"],
        "successful_jobs": ["build_fuzzilli_amd64", "build_fuzzilli_arm64"],
        "selected_docker_jobs": [
            "build_fuzzilli_amd64",
            "build_fuzzilli_arm64",
        ],
        "gates": {"selected_jobs": "success", "docker_latest": "success"},
        "complete": True,
        "publish": True,
        "artifacts": [
            {
                "key": "fuzzilli-amd64",
                "artifact_id": 801,
                "artifact_name": "orion-build-fuzzilli-amd64-2",
                "archive_path": "public/fuzzilli.tar.zst",
                "source_filename": "fuzzilli-amd64.tar.zst",
                "service": "fuzzilli",
                "arch": "amd64",
                "kind": "docker",
                "digest": "sha256:" + "1" * 64,
            },
            {
                "key": "fuzzilli-arm64",
                "artifact_id": 802,
                "artifact_name": "orion-build-fuzzilli-arm64-2",
                "archive_path": "public/fuzzilli.tar.zst",
                "source_filename": "fuzzilli-arm64.tar.zst",
                "service": "fuzzilli",
                "arch": "arm64",
                "kind": "docker",
                "digest": "sha256:" + "2" * 64,
            },
        ],
        "published_images": {
            "fuzzilli": {
                "architectures": {
                    "amd64": "sha256:" + "1" * 64,
                    "arm64": "sha256:" + "2" * 64,
                },
                "latest_published": True,
            },
        },
    }


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _publication_repo(root: Path) -> Path:
    root.mkdir()
    _git(root, "init", "-b", "master")
    _git(root, "config", "user.name", "Orion tests")
    _git(root, "config", "user.email", "orion-tests@example.invalid")
    files = {
        "services/docker/service.yaml": "name: docker\narch: [amd64, arm64]\n",
        "services/docker/Dockerfile": "FROM alpine:3.20\n",
        "services/windows/service.yaml": (
            "name: windows\ntype: msys\nbase: base.tar.xz\n"
        ),
        "services/windows/setup.sh": "#!/bin/sh\nexit 0\n",
        "services/brew/service.yaml": "name: brew\ntype: homebrew\nbase: base.tar.gz\n",
        "services/brew/setup.sh": "#!/bin/sh\nexit 0\n",
        "services/virtual/service.yaml": "name: virtual\ntype: test\n",
    }
    for name, contents in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "publication graph")
    return root


def test_import_task_ids_distinguish_artifacts_and_attempts(manifest) -> None:
    """Import task IDs must be unique across artifact keys and workflow attempts."""
    artifact = manifest["artifacts"][0]

    first = gha_publish.artifact_task_id(
        manifest["run_id"], manifest["run_attempt"], artifact["key"]
    )
    later_attempt = gha_publish.artifact_task_id(
        manifest["run_id"], "3", artifact["key"]
    )
    second_artifact = gha_publish.artifact_task_id(
        manifest["run_id"], manifest["run_attempt"], manifest["artifacts"][1]["key"]
    )

    assert first != later_attempt
    assert first != second_artifact
    assert len(first) == 22
    assert re.fullmatch(r"[A-Za-z0-9_-]{22}", first)
    assert first[8] in "QRST"


def test_manifest_must_match_the_exact_github_run(manifest) -> None:
    """Reject manifests whose run identity differs from the triggering workflow."""
    gha_publish.validate_manifest(
        manifest,
        repository="MozillaSecurity/orion",
        revision="a" * 40,
        event="push",
        branch="master",
        run_id="123456789",
        attempt="2",
    )

    for field, expected in (
        ("repository", "someone-else/orion"),
        ("revision", "b" * 40),
        ("event", "workflow_dispatch"),
        ("branch", "release"),
        ("run_id", "123456790"),
        ("run_attempt", "1"),
        ("workflow", "untrusted.yml"),
    ):
        invalid = {**manifest, field: expected}
        with pytest.raises((ValueError, TypeError)):
            gha_publish.validate_manifest(
                invalid,
                repository="MozillaSecurity/orion",
                revision="a" * 40,
                event="push",
                branch="master",
                run_id="123456789",
                attempt="2",
            )


def test_push_decision_finds_manifest_from_matching_workflow_run(
    manifest, monkeypatch
) -> None:
    """Select the manifest belonging to the exact matching push run."""
    repository = manifest["repository"]
    revision = manifest["revision"]
    expected_run = {
        "id": 123456789,
        "run_attempt": 2,
        "run_number": 418,
        "head_sha": revision,
        "event": "push",
        "head_branch": "master",
        "path": ".github/workflows/orion.yml",
    }
    runs = {
        "workflow_runs": [
            {**expected_run, "id": 111, "head_sha": "b" * 40},
            {**expected_run, "id": 112, "path": ".github/workflows/other.yml"},
            expected_run,
        ]
    }
    api_calls = []

    def github_json(url: str) -> dict[str, Any]:
        api_calls.append(url)
        if url.endswith(
            "/actions/runs?head_sha=" + revision + "&event=push&branch=master"
        ):
            return runs
        assert url.endswith("/actions/runs/123456789/artifacts")
        return {
            "artifacts": [
                {
                    "id": 900,
                    "name": "orion-publication-manifest-123456789-2",
                    "expired": False,
                    "digest": "sha256:" + "9" * 64,
                }
            ]
        }

    downloaded = []

    def download(
        artifact_id: int,
        filename: str,
        *,
        repository: str,
        digest: str | None = None,
    ) -> dict[str, Any]:
        assert repository == "MozillaSecurity/orion"
        assert digest == "sha256:" + "9" * 64
        downloaded.append((artifact_id, filename))
        return manifest

    monkeypatch.setattr(gha_publish, "_github_json", github_json)
    monkeypatch.setattr(gha_publish, "download_artifact_json", download)
    monkeypatch.setattr(gha_publish, "_token", lambda: "test-worker-token")
    monkeypatch.setattr(
        gha_publish,
        "_actions_artifacts",
        lambda _token, _repository, _run: [
            {
                "id": 801,
                "name": "orion-build-fuzzilli-amd64-2",
                "digest": "sha256:" + "1" * 64,
                "expired": False,
            },
            {
                "id": 802,
                "name": "orion-build-fuzzilli-arm64-2",
                "digest": "sha256:" + "2" * 64,
                "expired": False,
            },
        ],
    )
    event = {
        "repository": {"full_name": repository},
        "after": revision,
        "ref": "refs/heads/master",
    }

    assert gha_publish.find_manifest_for_event(event, "github-push") == manifest
    assert downloaded == [(900, "manifest.json")]
    assert len(api_calls) == 2

    matching_artifacts = [
        {
            "id": 801,
            "name": "orion-build-fuzzilli-amd64-2",
            "digest": "sha256:" + "1" * 64,
            "expired": False,
        },
        {
            "id": 802,
            "name": "orion-build-fuzzilli-arm64-2",
            "digest": "sha256:" + "2" * 64,
            "expired": False,
        },
    ]
    for broken in (
        [{**matching_artifacts[0], "id": 999}, matching_artifacts[1]],
        [
            {**matching_artifacts[0], "digest": "sha256:" + "3" * 64},
            matching_artifacts[1],
        ],
    ):
        monkeypatch.setattr(
            gha_publish,
            "_actions_artifacts",
            lambda _token, _repository, _run, broken=broken: broken,
        )
        with pytest.raises(ValueError, match="outside this run attempt"):
            gha_publish.find_manifest_for_event(event, "github-push")

    for bad_event, action in (
        ({**event, "ref": "refs/heads/release"}, "github-push"),
        (event, "github-pull-request"),
    ):
        with pytest.raises(ValueError, match="master push"):
            gha_publish.find_manifest_for_event(bad_event, action)


def test_push_decision_does_not_borrow_prior_run_when_manifest_is_not_ready(
    manifest, monkeypatch
) -> None:
    """Do not reuse an earlier run's manifest when the current run has none ready."""
    revision = manifest["revision"]
    requested_urls = []

    def github_json(url: str) -> dict[str, Any]:
        requested_urls.append(url)
        if "actions/runs?" in url:
            return {
                "workflow_runs": [
                    {
                        "id": 100,
                        "run_attempt": 1,
                        "run_number": 417,
                        "head_sha": "b" * 40,
                        "event": "push",
                        "head_branch": "master",
                        "path": ".github/workflows/orion.yml",
                    },
                    {
                        "id": 101,
                        "run_attempt": 1,
                        "run_number": 418,
                        "head_sha": revision,
                        "event": "push",
                        "head_branch": "master",
                        "path": ".github/workflows/orion.yml",
                    },
                ]
            }
        assert url.endswith("/actions/runs/101/artifacts")
        return {"artifacts": []}

    monkeypatch.setattr(gha_publish, "_github_json", github_json)
    event = {
        "repository": {"full_name": "MozillaSecurity/orion"},
        "after": revision,
        "ref": "refs/heads/master",
    }

    with pytest.raises(RuntimeError, match="No eligible Orion GHA manifest"):
        gha_publish.find_manifest_for_event(event, "github-push")

    assert requested_urls[-1].endswith("/actions/runs/101/artifacts")
    assert all("/runs/100/artifacts" not in url for url in requested_urls)

    monkeypatch.setenv("GITHUB_EVENT", json.dumps(event))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gha_publish",
            "decision",
            "--github-action",
            "github-push",
            "--task-group",
            "g" * 22,
        ],
    )
    monkeypatch.setattr(
        gha_publish,
        "find_manifest_for_event",
        lambda *_args: (_ for _ in ()).throw(
            RuntimeError("No eligible Orion GHA manifest found for revision")
        ),
    )
    monkeypatch.setattr(
        gha_publish,
        "create_tasks",
        lambda *_args: pytest.fail("early decision must not schedule stale tasks"),
    )

    # An early Taskcluster webhook exits cleanly; the GHA worker later schedules
    # the exact same run after its manifest and graph gates are ready.
    gha_publish.main()

    monkeypatch.setattr(
        gha_publish,
        "find_manifest_for_event",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("GitHub API unavailable")),
    )
    with pytest.raises(RuntimeError, match="GitHub API unavailable"):
        gha_publish.main()


def test_action_artifact_listing_paginates_without_repeating_a_page(
    monkeypatch,
) -> None:
    """List workflow artifacts across pages without requesting a page twice."""
    pages = []

    def open_url(request, timeout):
        from urllib.parse import parse_qs, urlparse

        page = parse_qs(urlparse(request.full_url).query)["page"][0]
        pages.append(page)
        assert timeout == 60
        if page == "1":
            body = {"artifacts": [{"id": number} for number in range(100)]}
        else:
            assert page == "2"
            body = {"artifacts": [{"id": 100}]}
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(gha_publish.urllib.request, "urlopen", open_url)

    result = gha_publish._actions_artifacts(
        "worker-token", "MozillaSecurity/orion", "77"
    )

    assert pages == ["1", "2"]
    assert len(result) == 101
    assert result[-1]["id"] == 100


def test_generated_manifest_maps_uploaded_member_to_canonical_tc_artifact(
    tmp_path, monkeypatch
) -> None:
    """Map each uploaded archive member to its canonical Taskcluster artifact entry."""
    repo = _publication_repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    for key, value in {
        "GITHUB_REPOSITORY": "MozillaSecurity/orion",
        "GITHUB_RUN_ID": "123456789",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_RUN_NUMBER": "418",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF_NAME": "master",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv(
        "ORION_JOB_RESULTS",
        json.dumps(
            {
                job: {"result": "success"}
                for job in (
                    job_id("build", "docker", "amd64"),
                    job_id("build", "docker", "arm64"),
                    job_id("build", "windows", "amd64"),
                    job_id("build", "brew", "amd64"),
                )
            }
        ),
    )
    uploaded_names = [
        "orion-build-docker-amd64-2",
        "orion-build-docker-arm64-2",
        "orion-build-windows-amd64-2",
        "orion-build-brew-amd64-2",
    ]
    uploaded = [
        {
            "id": 800 + i,
            "name": name,
            "digest": f"sha256:{i + 1:064x}",
        }
        for i, name in enumerate(uploaded_names)
    ]
    monkeypatch.setattr(
        gha_publish, "_actions_artifacts", lambda _token, _repository, _run: uploaded
    )
    plan = {
        "revision": "a" * 40,
        "publish": True,
        "selected_jobs": [
            job_id("build", "docker", "amd64"),
            job_id("build", "docker", "arm64"),
            job_id("build", "windows", "amd64"),
            job_id("build", "brew", "amd64"),
        ],
        "selected_docker_jobs": [],
    }

    manifest = gha_publish.create_manifest(plan, token="worker-token")
    entries = {item["key"]: item for item in manifest["artifacts"]}

    assert entries["docker-amd64"]["source_filename"] == "docker-amd64.tar.zst"
    assert entries["docker-amd64"]["archive_path"] == "public/docker.tar.zst"
    assert entries["docker-amd64"]["artifact_id"] == "800"
    assert entries["docker-amd64"]["digest"] == "sha256:" + f"{1:064x}"
    assert entries["docker-arm64"]["source_filename"] == "docker-arm64.tar.zst"
    assert entries["windows-amd64"]["source_filename"] == "msys2.tar.bz2"
    assert entries["windows-amd64"]["archive_path"] == "public/msys2.tar.bz2"
    assert entries["brew-amd64"]["source_filename"] == "homebrew.tar.bz2"
    assert entries["brew-amd64"]["archive_path"] == "public/homebrew.tar.bz2"
    assert "virtual-amd64" not in entries


@pytest.mark.parametrize("event", ["schedule", "workflow_dispatch"])
def test_native_only_manual_and_scheduled_publications_need_no_docker_digest(
    tmp_path, monkeypatch, event
) -> None:
    """Allow native-only manual and scheduled publications without Docker digests."""
    repo = _publication_repo(tmp_path / event)
    monkeypatch.chdir(repo)
    for key, value in {
        "GITHUB_REPOSITORY": "MozillaSecurity/orion",
        "GITHUB_RUN_ID": "123456789",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_NUMBER": "419",
        "GITHUB_EVENT_NAME": event,
        "GITHUB_REF_NAME": "master",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv(
        "ORION_JOB_RESULTS",
        json.dumps({job_id("build", "windows", "amd64"): {"result": "success"}}),
    )
    uploaded = [
        {
            "id": 901,
            "name": "orion-build-windows-amd64-1",
            "digest": "sha256:" + "a" * 64,
        }
    ]
    monkeypatch.setattr(
        gha_publish, "_actions_artifacts", lambda _token, _repo, _run: uploaded
    )

    manifest = gha_publish.create_manifest(
        {
            "revision": "d" * 40,
            "publish": True,
            "selected_jobs": [job_id("build", "windows", "amd64")],
            "selected_docker_jobs": [],
        },
        token="worker-token",
    )

    assert manifest["event"] == event
    assert manifest["publish"] is True
    assert [item["kind"] for item in manifest["artifacts"]] == ["msys"]
    assert manifest["published_images"] == {}
    assert manifest["selected_docker_jobs"] == []
    assert manifest["gates"] == {
        "selected_jobs": "success",
        "docker_latest": "not-required",
    }
    assert manifest["complete"] is True
    gha_publish.validate_manifest(
        manifest,
        repository="MozillaSecurity/orion",
        revision="d" * 40,
        event=event,
        branch="master",
    )


def test_partial_publication_imports_successful_branches_without_advancing_baseline(
    tmp_path, monkeypatch
) -> None:
    """Index successful branches while failed jobs leave the baseline unchanged."""
    repo = _publication_repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    for key, value in {
        "GITHUB_REPOSITORY": "MozillaSecurity/orion",
        "GITHUB_RUN_ID": "123456789",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_NUMBER": "419",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF_NAME": "master",
    }.items():
        monkeypatch.setenv(key, value)
    docker_amd64 = job_id("build", "docker", "amd64")
    docker_arm64 = job_id("build", "docker", "arm64")
    windows = job_id("build", "windows", "amd64")
    recipe = job_id("recipe_test", "broken")
    monkeypatch.setenv(
        "ORION_JOB_RESULTS",
        json.dumps(
            {
                docker_amd64: {"result": "success"},
                docker_arm64: {"result": "failure"},
                windows: {"result": "success"},
                recipe: {"result": "failure"},
                "publish-docker": {"result": "failure"},
            }
        ),
    )
    uploaded = [
        {
            "id": 901,
            "name": "orion-build-docker-amd64-1",
            "digest": "sha256:" + "a" * 64,
        },
        {
            "id": 902,
            "name": "orion-build-windows-amd64-1",
            "digest": "sha256:" + "b" * 64,
        },
    ]
    monkeypatch.setattr(
        gha_publish, "_actions_artifacts", lambda _token, _repo, _run: uploaded
    )

    manifest = gha_publish.create_manifest(
        {
            "revision": "d" * 40,
            "publish": True,
            "selected_jobs": [docker_amd64, docker_arm64, windows, recipe],
            "selected_docker_jobs": [docker_amd64, docker_arm64],
        },
        token="worker-token",
    )

    assert {item["key"] for item in manifest["artifacts"]} == {
        "docker-amd64",
        "windows-amd64",
    }
    assert manifest["successful_jobs"] == sorted([docker_amd64, windows])
    assert manifest["complete"] is False
    assert manifest["published_images"] == {}
    gha_publish.validate_manifest(
        manifest,
        repository="MozillaSecurity/orion",
        revision="d" * 40,
        event="push",
        branch="master",
    )

    tasks = gha_publish.build_import_tasks(
        manifest, "d" * 22, datetime(2026, 10, 13, tzinfo=timezone.utc)
    )
    assert len(tasks) == 2
    assert gha_publish.expected_import_task_ids(manifest) == [
        gha_publish.artifact_task_id("123456789", "1", "docker-amd64"),
        gha_publish.artifact_task_id("123456789", "1", "windows-amd64"),
    ]


def test_publication_state_uses_only_completed_baseline_and_checks_each_arch(
    tmp_path,
    monkeypatch,
) -> None:
    """Compare each architecture with its completed baseline image."""
    repo = _publication_repo(tmp_path / "repo")
    services = Services(GitRepo.from_existing(repo))
    revision = "c" * 40
    now = datetime(2026, 10, 13, tzinfo=timezone.utc)
    routes: list[str] = []
    index_tasks = {
        gha_publish.MARKER_ROUTE: "marker",
        "project.fuzzing.orion.docker.amd64.master": "docker-amd64",
        "project.fuzzing.orion.docker.arm64.master": "docker-arm64",
        "project.fuzzing.orion.windows.master": "windows",
        "project.fuzzing.orion.brew.master": "brew",
    }
    artifacts = {
        "marker": ("public/orion-publication.json", "2027-01-01T00:00:00Z"),
        "docker-amd64": ("public/docker.tar.zst", "2026-12-01T00:00:00Z"),
        "docker-arm64": ("public/docker.tar.zst", "2026-10-19T00:00:00Z"),
        "windows": ("public/msys2.tar.bz2", "2026-12-01T00:00:00Z"),
        "brew": ("public/homebrew.tar.bz2", "2026-12-01T00:00:00Z"),
    }

    class Index:
        def findTask(self, route):
            routes.append(route)
            result = {"taskId": index_tasks[route]}
            if route != gha_publish.MARKER_ROUTE:
                result["data"] = {
                    "repository": "MozillaSecurity/orion",
                    "revision": revision,
                    "dockerLatestPublished": True,
                    "runId": "123",
                    "runAttempt": "1",
                }
            return result

    class Queue:
        marker_state = "completed"

        def task(self, task_id):
            data = {"repository": "MozillaSecurity/orion", "revision": revision}
            return {
                "expires": "2027-01-01T00:00:00Z",
                "extra": {"index": {"data": data}} if task_id == "marker" else {},
            }

        def status(self, task_id):
            state = self.marker_state if task_id == "marker" else "completed"
            return {"status": {"state": state, "runs": [{"state": state}]}}

        def listLatestArtifacts(self, task_id):
            name, expires = artifacts[task_id]
            return {"artifacts": [{"name": name, "expires": expires}]}

    queue = Queue()
    state = gha_publish.publication_state(
        index=Index(), queue=queue, now=now, services=services
    )

    assert state == {
        "base_revision": revision,
        "expired_services": ["docker"],
        "docker_latest_failed": [],
        "incomplete_services": [],
        "service_revisions": {
            "docker": revision,
            "windows": revision,
            "brew": revision,
        },
        "service_runs": {
            "docker": (123, 1),
            "windows": (123, 1),
            "brew": (123, 1),
        },
    }
    assert "project.fuzzing.orion.docker.amd64.master" in routes
    assert "project.fuzzing.orion.docker.arm64.master" in routes
    assert "project.fuzzing.orion.virtual.master" not in routes

    def find_task(_self, route):
        result = {"taskId": index_tasks[route]}
        if route != gha_publish.MARKER_ROUTE:
            result["data"] = {
                "repository": "MozillaSecurity/orion",
                "revision": revision,
                "dockerLatestPublished": True,
                "runId": "123"
                if route == "project.fuzzing.orion.docker.arm64.master"
                else "124",
                "runAttempt": "1",
            }
        return result

    monkeypatch.setattr(Index, "findTask", find_task)
    state = gha_publish.publication_state(
        index=Index(), queue=queue, now=now, services=services
    )
    assert state["service_revisions"]["docker"] == revision
    assert state["docker_latest_failed"] == []
    assert state["incomplete_services"] == ["docker"]
    assert state["service_revisions"]["windows"] == revision

    def failed_latest(_self, route):
        result = {"taskId": index_tasks[route]}
        if route != gha_publish.MARKER_ROUTE:
            result["data"] = {
                "repository": "MozillaSecurity/orion",
                "revision": revision,
                "dockerLatestPublished": not route.startswith(
                    "project.fuzzing.orion.docker."
                ),
                "runId": "125",
                "runAttempt": "1",
            }
        return result

    monkeypatch.setattr(Index, "findTask", failed_latest)
    state = gha_publish.publication_state(
        index=Index(), queue=queue, now=now, services=services
    )
    assert state["docker_latest_failed"] == ["docker"]
    assert "docker" not in state["service_revisions"]
    queue.marker_state = "pending"
    state = gha_publish.publication_state(
        index=Index(), queue=queue, now=now, services=services
    )
    assert state["base_revision"] is None
    assert state["service_revisions"]["windows"] == revision


def test_planner_retries_incomplete_service_publication(tmp_path, monkeypatch):
    """Retry an unchanged service after an incomplete Docker publication."""
    repo = _publication_repo(tmp_path / "repo")
    revision = _git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(
        gha_publish,
        "publication_state",
        lambda: {
            "base_revision": revision,
            "expired_services": [],
            "service_revisions": {"docker": revision},
            "incomplete_services": ["docker"],
        },
    )

    plan = build_plan(
        repo,
        revision=revision,
        event="push",
        branch="master",
        baseline_from_taskcluster=True,
    )

    assert plan["services"] == ["docker"]
    assert job_id("build", "docker", "amd64") in plan["selected_jobs"]


def test_planner_uses_taskcluster_baseline_and_falls_back_to_full_graph(
    tmp_path, monkeypatch
) -> None:
    """Use indexed baselines for planning, or select the full graph if unavailable."""
    repo = _publication_repo(tmp_path / "repo")
    base_revision = _git(repo, "rev-parse", "HEAD")
    (repo / "services/docker/Dockerfile").write_text("FROM alpine:3.21\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "update docker")
    revision = _git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(
        gha_publish,
        "publication_state",
        lambda: {"base_revision": base_revision, "expired_services": []},
    )

    incremental = build_plan(
        repo,
        revision=revision,
        event="push",
        branch="master",
        baseline_from_taskcluster=True,
    )

    assert incremental["changed_paths"] == ["services/docker/Dockerfile"]
    assert incremental["services"] == ["docker"]

    monkeypatch.setattr(
        gha_publish,
        "publication_state",
        lambda: {"base_revision": None, "expired_services": ["virtual"]},
    )
    full = build_plan(
        repo,
        revision=revision,
        event="workflow_dispatch",
        branch="master",
        baseline_from_taskcluster=True,
    )

    assert full["full_rebuild_reason"] == "baseline-missing"
    assert {"docker", "windows", "brew", "virtual"} == set(full["services"])
    assert job_id("build", "docker", "amd64") in full["selected_jobs"]
    assert job_id("build", "docker", "arm64") in full["selected_jobs"]


def test_import_task_definitions_preserve_artifact_routes_and_marker_dependencies(
    manifest,
) -> None:
    """Preserve artifact index routes and marker-task dependencies in import tasks."""
    task_group = "d" * 22
    definitions = gha_publish.build_import_tasks(
        manifest,
        task_group,
        datetime(2026, 10, 13, tzinfo=timezone.utc),
    )

    amd64_id = gha_publish.artifact_task_id("123456789", "2", "fuzzilli-amd64")
    amd64 = definitions[amd64_id]
    assert amd64["extra"]["orion"]["artifactDigest"] == "sha256:" + "1" * 64
    assert amd64["extra"]["orion"]["dockerLatestPublished"] is True
    assert "index.project.fuzzing.orion.fuzzilli.amd64.master" in amd64["routes"]
    assert (
        "index.project.fuzzing.orion.fuzzilli.amd64.rev." + "a" * 40 in amd64["routes"]
    )
    assert "index.project.fuzzing.orion.fuzzilli.master" in amd64["routes"]
    assert "index.project.fuzzing.orion.fuzzilli.arm64.master" not in amd64["routes"]
    assert isinstance(amd64["payload"]["artifacts"], list)
    assert amd64["payload"]["artifacts"][0]["name"] == "public/fuzzilli.tar.zst"
    assert amd64["payload"]["command"][0][:3] == ["bash", "-e", "-c"]
    assert amd64["payload"]["artifacts"][0]["type"] == "file"
    assert amd64["payload"]["artifacts"][0]["path"] == "orion-import/artifact"

    arm64_id = gha_publish.artifact_task_id("123456789", "2", "fuzzilli-arm64")
    arm64 = definitions[arm64_id]
    assert "index.project.fuzzing.orion.fuzzilli.arm64.master" in arm64["routes"]
    assert "index.project.fuzzing.orion.fuzzilli.master" not in arm64["routes"]

    marker_id = gha_publish.artifact_task_id("123456789", "2", "publication-marker")
    marker = definitions[marker_id]
    assert set(marker["dependencies"]) == {amd64_id, arm64_id}
    assert marker["extra"]["index"]["rank"] == 12345678902
    assert marker["expires"].startswith("2027-04-13")


def _zip_bytes(entries: list[tuple[str, bytes]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return output.getvalue()


def test_import_download_uses_exact_artifact_id_and_private_token_file(
    tmp_path, monkeypatch
) -> None:
    """Download the selected artifact by ID using the private token file."""
    token_file = tmp_path / "github-token"
    token_file.write_text("ghp_test-secret\n")
    token_file.chmod(0o600)
    monkeypatch.setenv("ORION_GITHUB_TOKEN_FILE", str(token_file))
    archive_bytes = _zip_bytes([("fuzzilli-amd64.tar.zst", b"compressed image bytes")])
    requests = []

    def open_url(request, timeout):
        requests.append((request, timeout))
        return io.BytesIO(archive_bytes)

    monkeypatch.setattr(gha_publish.urllib.request, "urlopen", open_url)
    destination = tmp_path / "worker/artifact.tar.zst"

    gha_publish.import_artifact(
        "801", "MozillaSecurity/orion", "fuzzilli-amd64.tar.zst", destination
    )

    assert destination.read_bytes() == b"compressed image bytes"
    assert len(requests) == 1
    request, timeout = requests[0]
    assert request.full_url.endswith("/actions/artifacts/801/zip")
    assert request.get_header("Authorization") == "Bearer ghp_test-secret"
    assert timeout == 300


def test_artifact_bearer_header_is_not_forwarded_to_signed_redirect(
    tmp_path, monkeypatch
) -> None:
    """Keep the GitHub bearer token out of redirected signed-URL requests."""
    from http.client import HTTPMessage

    token_file = tmp_path / "github-token"
    token_file.write_text("ghp_redirect-test\n")
    token_file.chmod(0o600)
    monkeypatch.setenv("ORION_GITHUB_TOKEN_FILE", str(token_file))
    requests: list[urllib.request.Request] = []

    def open_url(request: urllib.request.Request, **_kwargs: Any) -> io.BytesIO:
        requests.append(request)
        return io.BytesIO(_zip_bytes([("fuzzilli-amd64.tar.zst", b"image")]))

    monkeypatch.setattr(
        gha_publish.urllib.request,
        "urlopen",
        open_url,
    )

    gha_publish.import_artifact(
        "801",
        "MozillaSecurity/orion",
        "fuzzilli-amd64.tar.zst",
        tmp_path / "artifact.tar.zst",
    )

    request = requests[0]
    assert request.get_header("Authorization") == "Bearer ghp_redirect-test"
    assert all(key.lower() != "authorization" for key in request.headers)
    redirected = urllib.request.HTTPRedirectHandler().redirect_request(
        request,
        io.BytesIO(),
        302,
        "Found",
        HTTPMessage(),
        "https://objects.example.invalid/artifact",
    )
    assert redirected is not None
    assert redirected.get_header("Authorization") is None


def test_import_command_quotes_untrusted_artifact_arguments(tmp_path) -> None:
    """Quote artifact arguments so untrusted names cannot alter the import command."""
    marker = tmp_path / "shell-injection-ran"
    payload = f"$(touch {marker})"
    script = gha_publish._download_script(
        {
            "artifact_id": payload,
            "repository": "MozillaSecurity/orion",
            "source_filename": payload,
            "worker_path": str(tmp_path / "destination.tar.zst"),
        }
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    captured = tmp_path / "arguments"
    (bin_dir / "git").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "python").write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$CAPTURE_ARGUMENTS"\n'
    )
    (bin_dir / "git").chmod(0o755)
    (bin_dir / "python").chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "RUNNER_TEMP": str(tmp_path),
        "TASK_ID": "safe-task-id",
        "ORION_REPOSITORY_URL": "https://github.com/MozillaSecurity/orion.git",
        "ORION_REVISION": "a" * 40,
        "CAPTURE_ARGUMENTS": str(captured),
    }

    subprocess.run(["/bin/bash", "-e", "-c", script], check=True, env=env)

    assert not marker.exists()
    args = captured.read_text().splitlines()
    assert args[args.index("--artifact-id") + 1] == payload
    assert args[args.index("--filename") + 1] == payload


def test_token_reader_rejects_group_or_world_readable_file(
    tmp_path, monkeypatch
) -> None:
    """Reject token files readable by group or other users."""
    token_file = tmp_path / "github-token"
    token_file.write_text("must-not-be-read")
    token_file.chmod(0o640)
    monkeypatch.setenv("ORION_GITHUB_TOKEN_FILE", str(token_file))

    with pytest.raises(PermissionError, match="mode 0600"):
        gha_publish._token()


@pytest.mark.parametrize(
    "entries",
    [
        [("wrong-name.tar.zst", b"wrong")],
        [
            ("fuzzilli-amd64.tar.zst", b"one"),
            ("duplicate/fuzzilli-amd64.tar.zst", b"two"),
        ],
        [
            ("fuzzilli-amd64.tar.zst", b"expected"),
            ("unexpected.txt", b"extra"),
        ],
    ],
    ids=["missing-expected-file", "duplicate-basename", "unexpected-file"],
)
def test_import_rejects_wrong_or_ambiguous_artifact_zip(
    tmp_path, monkeypatch, entries
) -> None:
    """Reject archives with unexpected or ambiguous artifact contents."""
    token_file = tmp_path / "github-token"
    token_file.write_text("test-token\n")
    token_file.chmod(0o600)
    monkeypatch.setenv("ORION_GITHUB_TOKEN_FILE", str(token_file))
    monkeypatch.setattr(
        gha_publish.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: io.BytesIO(_zip_bytes(entries)),
    )

    with pytest.raises(ValueError, match="Expected exactly root file"):
        gha_publish.import_artifact(
            "801",
            "MozillaSecurity/orion",
            "fuzzilli-amd64.tar.zst",
            tmp_path / "worker/artifact.tar.zst",
        )


def test_import_rejects_noncanonical_zip_path(tmp_path, monkeypatch) -> None:
    """Reject archive member paths that do not match the canonical artifact path."""
    token_file = tmp_path / "github-token"
    token_file.write_text("test-token\n")
    token_file.chmod(0o600)
    monkeypatch.setenv("ORION_GITHUB_TOKEN_FILE", str(token_file))
    monkeypatch.setattr(
        gha_publish.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: io.BytesIO(
            _zip_bytes([("nested/fuzzilli-amd64.tar.zst", b"payload")])
        ),
    )

    with pytest.raises(ValueError):
        gha_publish.import_artifact(
            "801",
            "MozillaSecurity/orion",
            "fuzzilli-amd64.tar.zst",
            tmp_path / "worker/artifact.tar.zst",
        )


def test_import_rejects_symlink_zip_member(tmp_path, monkeypatch) -> None:
    """Reject symlink members instead of extracting them as artifacts."""
    token_file = tmp_path / "github-token"
    token_file.write_text("test-token\n")
    token_file.chmod(0o600)
    monkeypatch.setenv("ORION_GITHUB_TOKEN_FILE", str(token_file))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        member = zipfile.ZipInfo("fuzzilli-amd64.tar.zst")
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(member, b"target")
    monkeypatch.setattr(
        gha_publish.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: io.BytesIO(output.getvalue()),
    )

    with pytest.raises(ValueError, match="regular file"):
        gha_publish.import_artifact(
            "801",
            "MozillaSecurity/orion",
            "fuzzilli-amd64.tar.zst",
            tmp_path / "worker/artifact.tar.zst",
        )


def test_monitor_raises_on_failed_task(manifest) -> None:
    """Report a failed Taskcluster import after checking every sibling task."""
    expected = set(gha_publish.expected_import_task_ids(manifest))
    failed_id = next(iter(expected))
    pending_id = next(task_id for task_id in expected if task_id != failed_id)
    pending_polls = 0

    class Queue:
        def status(self, task_id):
            nonlocal pending_polls
            if task_id == failed_id:
                return {"status": {"state": "failed", "runs": [{"state": "failed"}]}}
            if task_id == pending_id:
                pending_polls += 1
                if pending_polls == 1:
                    return {
                        "status": {
                            "state": "running",
                            "runs": [{"state": "running"}],
                        }
                    }
            return {"status": {"state": "completed", "runs": [{"state": "completed"}]}}

    with pytest.raises(RuntimeError, match="ended failed"):
        gha_publish.monitor_imports(manifest, queue=Queue(), timeout=1, poll_interval=0)
    assert pending_polls == 2


def test_monitor_does_not_treat_an_idle_worker_as_success(
    manifest, monkeypatch
) -> None:
    """Keep monitoring an idle worker rather than reporting premature success."""
    marker_id = gha_publish.artifact_task_id(
        manifest["run_id"], manifest["run_attempt"], "publication-marker"
    )

    class Queue:
        def status(self, task_id):
            if task_id == marker_id:
                return {"status": {"state": "pending", "runs": []}}
            return {"status": {"state": "completed", "runs": [{"state": "completed"}]}}

    times = iter([0.0, 0.0, 0.0, 2.0])
    monkeypatch.setattr(gha_publish.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(gha_publish.time, "sleep", lambda _seconds: None)

    with pytest.raises(TimeoutError, match="publication tasks"):
        gha_publish.monitor_imports(manifest, queue=Queue(), timeout=1, poll_interval=0)


def test_taskcluster_hook_renders_only_master_push_publication_decisions() -> None:
    """Restrict the Taskcluster hook to publication decisions for master pushes."""
    config = safe_load((Path(__file__).parents[3] / ".taskcluster.yml").read_text())

    def tasks(tasks_for: str, event: dict[str, Any]) -> list[dict[str, Any]]:
        rendered = jsone_render(
            config,
            context={
                "taskcluster_root_url": "https://community-tc.services.mozilla.com",
                "tasks_for": tasks_for,
                "as_slugid": lambda: "a" * 22,
                "event": event,
                "now": "2026-10-13T00:00:00.000Z",
            },
        )
        return rendered.get("tasks", [])

    master_push = tasks(
        "github-push",
        {
            "repository": {"full_name": "MozillaSecurity/orion"},
            "ref": "refs/heads/master",
            "after": "a" * 40,
        },
    )
    assert len(master_push) == 1
    assert master_push[0]["workerType"] == "orion-gha-publish"

    assert tasks("github-push", {"ref": "refs/heads/feature", "after": "b" * 40}) == []
    assert tasks("github-pull-request", {"action": "opened", "number": 12}) == []
    assert tasks("github-release", {"action": "published"}) == []


@pytest.mark.parametrize(
    (
        "graph",
        "publish",
        "manifest",
        "worker",
        "docker_required",
        "docker",
        "expected_returncode",
    ),
    [
        ("success", "false", "skipped", "skipped", "true", "skipped", 0),
        ("success", "true", "skipped", "skipped", "false", "skipped", 1),
        ("success", "true", "success", "skipped", "false", "skipped", 1),
        ("success", "true", "success", "success", "false", "skipped", 0),
        ("success", "true", "success", "success", "true", "failure", 1),
        ("failure", "false", "skipped", "skipped", "false", "skipped", 1),
        ("failure", "true", "success", "success", "false", "skipped", 1),
    ],
    ids=[
        "nonpublish-pr-skips-worker",
        "publish-requires-manifest",
        "publish-requires-import-worker",
        "publish-all-gates-pass",
        "docker-publication-failure",
        "graph-failure-no-green-pr",
        "graph-failure-no-green-publish",
    ],
)
def test_generated_result_step_enforces_graph_and_publication_statuses(
    tmp_path,
    graph,
    publish,
    manifest,
    worker,
    docker_required,
    docker,
    expected_returncode,
) -> None:
    """Require graph, Docker, and Taskcluster success for a green publish run."""
    repo = _publication_repo(tmp_path / "repo")
    jobs = safe_load(
        render_workflow(Services(GitRepo.from_existing(repo))).split("\n", 3)[3]
    )["jobs"]
    command = jobs["result"]["steps"][0]["run"]
    env = {
        "PATH": os.environ["PATH"],
        "ORION_GRAPH_RESULT": graph,
        "ORION_PUBLISH": publish,
        "ORION_MANIFEST_RESULT": manifest,
        "ORION_WORKER_RESULT": worker,
        "ORION_DOCKER_REQUIRED": docker_required,
        "ORION_DOCKER_RESULT": docker,
    }

    completed = subprocess.run(
        ["/bin/bash", "-e", "-c", command],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == expected_returncode
