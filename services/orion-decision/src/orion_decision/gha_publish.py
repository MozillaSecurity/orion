# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Import exact GitHub Actions artifacts into Taskcluster publication routes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import time
import urllib.request
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from taskcluster.exceptions import TaskclusterFailure

from . import (
    ARTIFACTS_EXPIRE,
    DEADLINE,
    OWNER_EMAIL,
    PROVISIONER_ID,
    SOURCE_URL,
    Taskcluster,
)

QUEUE = "orion-gha-publish"
WORKER = "orion-gha-publish"
WORKER_CLIENT = "project/fuzzing/worker-orion-gha-publish-gh"
MARKER_ROUTE = "project.fuzzing.orion.gha.master"
MANIFEST_SCHEMA = 1


def artifact_task_id(run_id: str, attempt: str | int, key: str) -> str:
    """Return a stable Taskcluster ID for one artifact in one workflow attempt."""
    digest = hashlib.sha256(f"{run_id}:{attempt}:{key}".encode()).digest()[:16]
    import base64

    tc_uuid = uuid.UUID(bytes=digest, version=4)
    return base64.urlsafe_b64encode(tc_uuid.bytes).decode().rstrip("=")


def publication_rank(run_id: str | int, attempt: str | int) -> int:
    """Give later GHA run IDs and retries a strictly higher Taskcluster rank."""
    attempt_number = int(attempt)
    if not 1 <= attempt_number <= 99:
        raise ValueError("GitHub Actions run attempt must be between 1 and 99")
    return int(run_id) * 100 + attempt_number


def validate_manifest(
    manifest: dict[str, Any],
    *,
    repository: str,
    revision: str,
    event: str,
    branch: str,
    run_id: str | None = None,
    attempt: str | int | None = None,
) -> None:
    """Reject a publication manifest that does not describe the requested run."""
    expected = {
        "schema": MANIFEST_SCHEMA,
        "repository": repository,
        "revision": revision,
        "event": event,
        "branch": branch,
        "workflow": "orion.yml",
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(
                f"Publication manifest {key}={manifest.get(key)!r}; expected {value!r}"
            )
    if run_id is not None and str(manifest.get("run_id")) != str(run_id):
        raise ValueError("Publication manifest belongs to a different GitHub run")
    if attempt is not None and str(manifest.get("run_attempt")) != str(attempt):
        raise ValueError("Publication manifest belongs to a different run attempt")
    if not manifest.get("publish"):
        raise ValueError("This workflow run is not eligible to publish")
    if not isinstance(manifest.get("artifacts"), list):
        raise ValueError("Publication manifest has no artifact list")
    seen: set[str] = set()
    for artifact in manifest["artifacts"]:
        if not isinstance(artifact, dict) or not artifact.get("artifact_id"):
            raise ValueError("Publication manifest contains an artifact without an ID")
        key = str(artifact.get("key", ""))
        if not key or key in seen:
            raise ValueError(f"Publication manifest has duplicate/empty key {key!r}")
        seen.add(key)
        if artifact.get("kind") not in {"docker", "msys", "homebrew"}:
            raise ValueError(
                f"Unsupported publication artifact kind: {artifact.get('kind')!r}"
            )
        if not artifact.get("archive_path") or not artifact.get("source_filename"):
            raise ValueError(
                "Publication manifest artifact is missing its archive filename"
            )
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(artifact.get("service", ""))):
            raise ValueError("Publication manifest has an invalid service name")
        if artifact.get("kind") == "docker" and artifact.get("arch") not in {
            "amd64",
            "arm64",
        }:
            raise ValueError("Publication manifest has an invalid Docker architecture")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(artifact.get("digest", ""))):
            raise ValueError(
                "Publication manifest artifact is missing its SHA-256 digest"
            )
    expected_gates = {
        "selected_jobs": "success",
        "docker_latest": "success"
        if manifest.get("selected_docker_jobs")
        else "not-required",
    }
    if manifest.get("gates") != expected_gates:
        raise ValueError(
            "Publication manifest does not prove the required GHA gates succeeded"
        )


def _artifact_indexes(manifest: dict[str, Any], item: dict[str, Any]) -> list[str]:
    service = item["service"]
    revision = manifest["revision"]
    branch = manifest["branch"]
    if item["kind"] == "docker":
        arch = item["arch"]
        routes = [
            f"index.project.fuzzing.orion.{service}.{arch}.{branch}",
            f"index.project.fuzzing.orion.{service}.{arch}.rev.{revision}",
        ]
        if arch == "amd64":
            routes.extend(
                [
                    f"index.project.fuzzing.orion.{service}.{branch}",
                    f"index.project.fuzzing.orion.{service}.rev.{revision}",
                ]
            )
        return routes
    return [
        f"index.project.fuzzing.orion.{service}.{branch}",
        f"index.project.fuzzing.orion.{service}.rev.{revision}",
    ]


def _download_script(item: dict[str, Any]) -> str:
    """Use the pinned checkout's helper from this task's exact repository SHA."""
    return "\n".join(
        [
            "set -eu",
            'work="$(mktemp -d .orion-import.XXXXXX)"',
            "trap 'rm -rf \"$work\"' EXIT",
            'git -C "$work" init -q',
            'git -C "$work" remote add origin "$ORION_REPOSITORY_URL"',
            'git -C "$work" fetch -q --depth=1 origin "$ORION_REVISION"',
            'git -C "$work" checkout -q FETCH_HEAD',
            'export PYTHONPATH="$work/services/orion-decision/src"',
            "python -m orion_decision.gha_publish import-artifact "
            f"--artifact-id {shlex.quote(str(item['artifact_id']))} "
            f"--repository {shlex.quote(str(item['repository']))} "
            f"--filename {shlex.quote(str(item['source_filename']))} "
            f"--digest {shlex.quote(str(item.get('digest') or ''))} "
            f"--destination {shlex.quote(str(item['worker_path']))}",
        ]
    )


def build_import_tasks(
    manifest: dict[str, Any],
    task_group: str,
    now: datetime,
    *,
    token_file: str = "$ORION_GITHUB_TOKEN_FILE",
    repo_url: str = SOURCE_URL,
) -> dict[str, dict[str, Any]]:
    """Build ordinary generic-worker artifact-holder tasks and a baseline marker."""
    validate_manifest(
        manifest,
        repository=manifest["repository"],
        revision=manifest["revision"],
        event=manifest["event"],
        branch=manifest["branch"],
        run_id=manifest["run_id"],
        attempt=manifest["run_attempt"],
    )
    expires = (now.astimezone(timezone.utc) + ARTIFACTS_EXPIRE).isoformat()
    deadline = (now.astimezone(timezone.utc) + DEADLINE).isoformat()
    tasks: dict[str, dict[str, Any]] = {}
    task_ids: list[str] = []
    for item in manifest["artifacts"]:
        item = {**item, "repository": manifest["repository"]}
        item.setdefault("worker_path", "orion-import/artifact")
        item.setdefault(
            "source_filename",
            f"{item['service']}-{item['arch']}.tar.zst"
            if item["kind"] == "docker"
            else Path(item["archive_path"]).name,
        )
        task_id = artifact_task_id(
            str(manifest["run_id"]), manifest["run_attempt"], str(item["key"])
        )
        task_ids.append(task_id)
        output_name = Path(item["archive_path"]).name
        rank = publication_rank(manifest["run_id"], manifest["run_attempt"])
        provenance = {
            "revision": manifest["revision"],
            "repository": manifest["repository"],
            "runId": str(manifest["run_id"]),
            "runAttempt": str(manifest["run_attempt"]),
            "runNumber": int(manifest["run_number"]),
            "artifactId": str(item["artifact_id"]),
            "artifactKey": item["key"],
            "artifactDigest": item.get("digest"),
        }
        task_name = f"Orion import {item['service']} {item.get('arch', '')}".strip()
        task = {
            "taskGroupId": task_group,
            "dependencies": [],
            "created": now.isoformat(),
            "deadline": deadline,
            "expires": expires,
            "provisionerId": PROVISIONER_ID,
            "workerType": WORKER,
            "schedulerId": "taskcluster-github",
            "routes": _artifact_indexes(manifest, item),
            "payload": {
                "maxRunTime": 3600,
                "command": [["bash", "-e", "-c", _download_script(item)]],
                "env": {
                    "ORION_REPOSITORY_URL": repo_url,
                    "ORION_REVISION": manifest["revision"],
                    "ORION_ARTIFACT_ID": str(item["artifact_id"]),
                },
                "artifacts": [
                    {
                        "name": f"public/{output_name}",
                        "type": "file",
                        "path": item["worker_path"],
                        "expires": expires,
                    }
                ],
            },
            "scopes": ["queue:scheduler-id:taskcluster-github"],
            "metadata": {
                "name": task_name,
                "description": (
                    "Import an exact GitHub Actions artifact into "
                    "Orion Taskcluster publication"
                ),
                "owner": OWNER_EMAIL,
                "source": SOURCE_URL,
            },
            "extra": {
                "index": {"rank": rank, "data": provenance},
                "orion": provenance,
            },
        }
        tasks[task_id] = task

    marker_id = artifact_task_id(
        str(manifest["run_id"]), manifest["run_attempt"], "publication-marker"
    )
    marker_path = "orion-import/publication.json"
    marker = {
        "revision": manifest["revision"],
        "repository": manifest["repository"],
        "event": manifest["event"],
        "branch": manifest["branch"],
        "run_id": str(manifest["run_id"]),
        "run_attempt": str(manifest["run_attempt"]),
        "run_number": int(manifest["run_number"]),
        "artifact_task_ids": task_ids,
        "published_images": manifest.get("published_images", {}),
    }
    marker_script = (
        "mkdir -p orion-import && cat > orion-import/publication.json "
        "<<'ORION_MARKER'\n" + json.dumps(marker, sort_keys=True) + "\nORION_MARKER"
    )
    tasks[marker_id] = {
        "taskGroupId": task_group,
        "dependencies": task_ids,
        "created": now.isoformat(),
        "deadline": deadline,
        "expires": expires,
        "provisionerId": PROVISIONER_ID,
        "workerType": WORKER,
        "schedulerId": "taskcluster-github",
        "routes": [f"index.{MARKER_ROUTE}"],
        "payload": {
            "maxRunTime": 3600,
            "command": [["bash", "-e", "-c", marker_script]],
            "artifacts": [
                {
                    "name": "public/orion-publication.json",
                    "type": "file",
                    "path": marker_path,
                    "expires": expires,
                }
            ],
        },
        "scopes": ["queue:scheduler-id:taskcluster-github"],
        "metadata": {
            "name": "Orion successful publication marker",
            "description": "Marks a fully imported Orion GHA publication baseline",
            "owner": OWNER_EMAIL,
            "source": SOURCE_URL,
        },
        "extra": {
            "index": {
                "rank": publication_rank(manifest["run_id"], manifest["run_attempt"]),
                "data": marker,
            },
            "orion": marker,
        },
    }
    return tasks


def expected_import_task_ids(manifest: dict[str, Any]) -> list[str]:
    """Return IDs for every expected import and the final success marker."""
    ids = [
        artifact_task_id(
            str(manifest["run_id"]), manifest["run_attempt"], str(item["key"])
        )
        for item in manifest["artifacts"]
    ]
    ids.append(
        artifact_task_id(
            str(manifest["run_id"]), manifest["run_attempt"], "publication-marker"
        )
    )
    return ids


def _actions_artifacts(
    token: str, repository: str, run_id: str
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    page = 1
    while True:
        request = urllib.request.Request(
            f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100&page={page}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            batch = json.load(response).get("artifacts", [])
        result.extend(batch)
        if len(batch) < 100:
            return result
        page += 1


def publication_state(
    *,
    index: Any | None = None,
    queue: Any | None = None,
    now: datetime | None = None,
    services: Any | None = None,
) -> dict[str, Any]:
    """Read the last fully imported baseline and identify expiring real archives."""
    from dateutil.parser import isoparse

    from .git import GitRepo
    from .orion import ServiceHomebrew, ServiceMsys, Services, ServiceTestOnly

    index = index or Taskcluster.get_service("index")
    queue = queue or Taskcluster.get_service("queue")
    now = now or datetime.now(timezone.utc)
    services = services or Services(GitRepo.from_existing(Path.cwd()))
    baseline = None
    try:
        marker = index.findTask(MARKER_ROUTE)
        marker_task_id = marker["taskId"]
        marker_task = queue.task(marker_task_id)
        status = queue.status(marker_task_id)
        status = status.get("status", status)
        marker_artifacts = queue.listLatestArtifacts(marker_task_id).get(
            "artifacts", []
        )
        marker_file = next(
            (
                item
                for item in marker_artifacts
                if item.get("name") == "public/orion-publication.json"
            ),
            None,
        )
        data = marker.get("data") or marker_task.get("extra", {}).get("index", {}).get(
            "data"
        )
        if (
            status.get("state") == "completed"
            and status.get("runs", [{}])[-1].get("state") == "completed"
            and marker_file
            and data
            and data.get("repository") == "MozillaSecurity/orion"
        ):
            baseline = data.get("revision")
    except Exception as exc:
        if getattr(exc, "status_code", None) != 404:
            raise

    next_run = now + timedelta(days=7)
    expired: list[str] = []
    for service in services.values():
        if isinstance(service, ServiceTestOnly):
            continue
        archs = (
            [None]
            if isinstance(service, (ServiceHomebrew, ServiceMsys))
            else service.archs
        )
        for arch in archs:
            route = f"project.fuzzing.orion.{service.name}"
            if arch:
                route += f".{arch}"
            route += ".master"
            try:
                task_id = index.findTask(route)["taskId"]
                task = queue.task(task_id)
                task_expires = isoparse(task["expires"])
                artifact_name = (
                    "public/msys2.tar.bz2"
                    if isinstance(service, ServiceMsys)
                    else "public/homebrew.tar.bz2"
                    if isinstance(service, ServiceHomebrew)
                    else f"public/{service.name}.tar.zst"
                )
                artifacts = queue.listLatestArtifacts(task_id).get("artifacts", [])
                artifact = next(
                    (item for item in artifacts if item.get("name") == artifact_name),
                    None,
                )
                if (
                    artifact is None
                    or min(task_expires, isoparse(artifact["expires"])) < next_run
                ):
                    expired.append(service.name)
                    break
            except Exception as exc:
                if getattr(exc, "status_code", None) == 404:
                    expired.append(service.name)
                    break
                raise
    return {"base_revision": baseline, "expired_services": sorted(set(expired))}


def create_manifest(plan: dict[str, Any], *, token: str) -> dict[str, Any]:
    """Bind selected successful GHA build artifacts to this exact workflow attempt."""
    from .gha_plan import job_id
    from .git import GitRepo
    from .orion import ServiceHomebrew, ServiceMsys, Services, ServiceTestOnly

    repo = Path.cwd()
    services = Services(GitRepo.from_existing(repo))
    repository = os.environ["GITHUB_REPOSITORY"]
    revision = plan["revision"]
    run_id = str(os.environ["GITHUB_RUN_ID"])
    attempt = str(os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
    artifacts = _actions_artifacts(token, repository, run_id)
    by_name = {item["name"]: item for item in artifacts if not item.get("expired")}
    selected = set(plan.get("selected_jobs", []))
    entries: list[dict[str, Any]] = []
    for service in sorted(services.values(), key=lambda item: item.name):
        if isinstance(service, ServiceTestOnly):
            continue
        for arch in service.archs:
            if job_id("build", service.name, arch) not in selected:
                continue
            name = f"orion-build-{service.name}-{arch}-{attempt}"
            artifact = by_name.get(name)
            if artifact is None:
                raise ValueError(
                    f"Selected build artifact {name!r} is missing; rerun all jobs "
                    "so this workflow attempt has a complete artifact set"
                )
            native = isinstance(service, (ServiceMsys, ServiceHomebrew))
            entries.append(
                {
                    "key": f"{service.name}-{arch}",
                    "artifact_id": str(artifact["id"]),
                    "artifact_name": name,
                    "archive_path": (
                        "public/msys2.tar.bz2"
                        if isinstance(service, ServiceMsys)
                        else "public/homebrew.tar.bz2"
                        if isinstance(service, ServiceHomebrew)
                        else f"public/{service.name}.tar.zst"
                    ),
                    "source_filename": (
                        f"{service.name}-{arch}.tar.zst"
                        if not native
                        else "msys2.tar.bz2"
                        if isinstance(service, ServiceMsys)
                        else "homebrew.tar.bz2"
                    ),
                    "service": service.name,
                    "arch": arch,
                    "kind": (
                        "msys"
                        if isinstance(service, ServiceMsys)
                        else "homebrew"
                        if isinstance(service, ServiceHomebrew)
                        else "docker"
                    ),
                    "digest": _required_artifact_digest(artifact),
                }
            )
    published_images: dict[str, Any] = {}
    if plan.get("selected_docker_jobs"):
        digest_name = f"orion-published-image-digests-{run_id}-{attempt}"
        digest_artifact = by_name.get(digest_name)
        if digest_artifact is None:
            raise ValueError("Successful Docker publication digest artifact is missing")
        with TemporaryDirectory(prefix="orion-gha-digests-") as tmp:
            zip_path = Path(tmp) / "digests.zip"
            _download_artifact_zip(
                digest_artifact["id"],
                repository,
                zip_path,
                token=token,
                digest=_required_artifact_digest(digest_artifact),
            )
            with zipfile.ZipFile(zip_path) as archive:
                names = [
                    name
                    for name in archive.namelist()
                    if Path(name).name == "published-images.json"
                ]
                if len(names) != 1:
                    raise ValueError(
                        "Docker digest artifact has no unique published-images.json"
                    )
                published_images = json.loads(archive.read(names[0]))
    return {
        "schema": MANIFEST_SCHEMA,
        "repository": repository,
        "revision": revision,
        "run_id": run_id,
        "run_attempt": attempt,
        "run_number": int(os.environ["GITHUB_RUN_NUMBER"]),
        "event": os.environ["GITHUB_EVENT_NAME"],
        "branch": os.environ["GITHUB_REF_NAME"],
        "workflow": "orion.yml",
        "selected_jobs": sorted(selected),
        "selected_docker_jobs": sorted(plan.get("selected_docker_jobs", [])),
        "publish": bool(plan.get("publish"))
        and os.environ["GITHUB_REF_NAME"] == "master",
        "gates": {
            "selected_jobs": "success",
            "docker_latest": "success"
            if plan.get("selected_docker_jobs")
            else "not-required",
        },
        "artifacts": entries,
        "published_images": published_images,
    }


def _write_manifest(path: Path, plan_path: Path) -> None:
    plan = json.loads(plan_path.read_text())
    token = os.environ["GITHUB_TOKEN"]
    manifest = create_manifest(plan, token=token)
    if not manifest["publish"]:
        raise ValueError("GHA manifest generation is only for publication runs")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n")


def monitor_imports(
    manifest: dict[str, Any],
    *,
    queue: Any | None = None,
    timeout: float = 3600,
    poll_interval: float = 10,
) -> None:
    """Wait for this run's exact imports and marker; fail on missing/failed tasks."""
    queue = queue or Taskcluster.get_service("queue")
    expected = expected_import_task_ids(manifest)
    deadline = time.monotonic() + timeout
    pending = set(expected)
    while pending and time.monotonic() < deadline:
        for task_id in tuple(pending):
            try:
                response = queue.status(task_id)
                status = response.get("status", response)
            except Exception as exc:  # task may not have been inserted yet
                if getattr(exc, "status_code", None) == 404:
                    continue
                raise
            state = status.get("state")
            if state in {"failed", "exception", "canceled"}:
                raise RuntimeError(
                    f"Taskcluster publication task {task_id} ended {state}"
                )
            if state == "completed":
                if status.get("runs", [{}])[-1].get("state") != "completed":
                    raise RuntimeError(
                        f"Taskcluster publication task {task_id} did not complete"
                    )
                pending.remove(task_id)
        if pending:
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
    if pending:
        raise TimeoutError(
            "Timed out waiting for Taskcluster publication tasks: "
            + ", ".join(sorted(pending))
        )


def _token() -> str:
    path = Path(os.environ["ORION_GITHUB_TOKEN_FILE"])
    if path.stat().st_mode & 0o077:
        raise PermissionError("GitHub token file must be private (mode 0600)")
    return path.read_text().strip()


def _github_request(url: str, token: str, accept: str = "application/vnd.github+json"):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "orion-gha-publisher",
        },
    )
    # urllib's default redirect handler forwards Authorization to signed blob
    # storage on a different host. Unredirected headers are dropped on redirects.
    request.add_unredirected_header("Authorization", f"Bearer {token}")
    return request


def _github_json(url: str) -> dict[str, Any]:
    request = _github_request(url, _token())
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def find_manifest_for_event(
    event: dict[str, Any], github_action: str
) -> dict[str, Any]:
    """Find the exact eligible GHA run/artifact for a Taskcluster push event."""
    repository = event.get("repository", {}).get("full_name")
    revision = event.get("after")
    branch = str(event.get("ref", "")).removeprefix("refs/heads/")
    if (
        repository != "MozillaSecurity/orion"
        or not revision
        or branch != "master"
        or github_action != "github-push"
    ):
        raise ValueError(
            "Taskcluster publication decision requires a master push event"
        )
    base = f"https://api.github.com/repos/{repository}"
    runs = _github_json(
        f"{base}/actions/runs?head_sha={revision}&event=push&branch=master"
    )
    matches = [
        run
        for run in runs.get("workflow_runs", [])
        if run.get("head_sha") == revision
        and run.get("event") == "push"
        and run.get("head_branch") == "master"
        and run.get("path", "").endswith(".github/workflows/orion.yml")
    ]
    for run in sorted(matches, key=lambda item: int(item["run_number"]), reverse=True):
        artifacts = _github_json(f"{base}/actions/runs/{run['id']}/artifacts")
        manifest_name = f"orion-publication-manifest-{run['id']}-{run['run_attempt']}"
        artifact = next(
            (
                item
                for item in artifacts.get("artifacts", [])
                if item.get("name") == manifest_name and not item.get("expired")
            ),
            None,
        )
        if artifact is None:
            continue
        manifest = download_artifact_json(
            artifact["id"],
            "manifest.json",
            repository=repository,
            digest=_required_artifact_digest(artifact),
        )
        validate_manifest(
            manifest,
            repository=repository,
            revision=revision,
            event="push",
            branch="master",
            run_id=run["id"],
            attempt=run["run_attempt"],
        )
        if int(manifest["run_number"]) != int(run["run_number"]):
            raise ValueError("Publication manifest run number does not match GHA run")
        run_artifacts = _actions_artifacts(_token(), repository, str(run["id"]))
        artifacts_by_id = {str(item["id"]): item for item in run_artifacts}
        expected_builds = {
            item
            for item in manifest.get("selected_jobs", [])
            if item.startswith("build_")
        }
        recorded_builds: set[str] = set()
        from .gha_plan import job_id

        for item in manifest["artifacts"]:
            name = f"orion-build-{item['service']}-{item['arch']}-{run['run_attempt']}"
            record = artifacts_by_id.get(str(item["artifact_id"]))
            if (
                record is None
                or record.get("name") != name
                or item.get("artifact_name") != name
                or record.get("expired")
                or item.get("digest") != record.get("digest")
            ):
                raise ValueError(
                    "Publication manifest references an artifact outside "
                    "this run attempt"
                )
            recorded_builds.add(job_id("build", item["service"], item["arch"]))
        if recorded_builds != expected_builds:
            raise ValueError(
                "Publication manifest artifact IDs do not match selected build jobs"
            )
        return manifest
    raise RuntimeError(f"No eligible Orion GHA manifest found for {revision}")


def download_artifact_json(
    artifact_id: str | int,
    filename: str,
    repository: str | None = None,
    digest: str | None = None,
) -> dict[str, Any]:
    """Download one exact GitHub artifact ID, then read the named ZIP member."""
    repository = repository or os.environ.get("GITHUB_REPOSITORY")
    if not repository:
        raise RuntimeError("GITHUB_REPOSITORY is required")
    with TemporaryDirectory(prefix="orion-gha-artifact-") as tmp:
        path = Path(tmp) / "artifact.zip"
        _download_artifact_zip(artifact_id, repository, path, digest=digest)
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) != 1 or infos[0].filename != filename:
                raise ValueError(
                    f"Expected root file {filename!r} in artifact {artifact_id}"
                )
            mode = infos[0].external_attr >> 16
            if stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
                raise ValueError(f"Artifact member {filename!r} is not a regular file")
            return json.loads(archive.read(infos[0]))


def import_artifact(
    artifact_id: str,
    repository: str,
    filename: str,
    destination: Path,
    digest: str | None = None,
) -> None:
    """Fetch one exact run artifact member into the generic-worker upload path."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="orion-gha-import-") as tmp:
        zip_path = Path(tmp) / "artifact.zip"
        _download_artifact_zip(
            artifact_id,
            repository,
            zip_path,
            digest=digest,
            timeout=300,
        )
        with zipfile.ZipFile(zip_path) as archive:
            infos = archive.infolist()
            if len(infos) != 1 or infos[0].filename != filename:
                raise ValueError(
                    f"Expected exactly root file {filename!r} in artifact "
                    f"{artifact_id}; "
                    f"found {[item.filename for item in infos]}"
                )
            mode = infos[0].external_attr >> 16
            if stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
                raise ValueError(f"Artifact member {filename!r} is not a regular file")
            with archive.open(infos[0]) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)


def _download_artifact_zip(
    artifact_id: str | int,
    repository: str,
    destination: Path,
    *,
    token: str | None = None,
    digest: str | None = None,
    timeout: int = 120,
) -> None:
    request = _github_request(
        f"https://api.github.com/repos/{repository}/actions/artifacts/{artifact_id}/zip",
        token or _token(),
    )
    digest_hash = hashlib.sha256()
    with (
        urllib.request.urlopen(request, timeout=timeout) as response,
        destination.open("wb") as output,
    ):
        while chunk := response.read(1024 * 1024):
            digest_hash.update(chunk)
            output.write(chunk)
    if digest:
        actual = "sha256:" + digest_hash.hexdigest()
        if actual != digest:
            raise ValueError(
                f"GitHub artifact digest mismatch: expected {digest}, got {actual}"
            )


def _required_artifact_digest(artifact: dict[str, Any]) -> str:
    digest = artifact.get("digest")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("GitHub artifact metadata is missing a valid SHA-256 digest")
    return digest


def create_tasks(manifest: dict[str, Any], task_group: str) -> list[str]:
    """Insert deterministic tasks, treating an identical retry as idempotent."""
    queue = Taskcluster.get_service("queue")
    now = datetime.now(timezone.utc)
    tasks = build_import_tasks(manifest, task_group, now)
    for task_id, task in tasks.items():
        try:
            queue.createTask(task_id, task)
        except TaskclusterFailure as exc:
            if getattr(exc, "status_code", None) not in {409, 412}:
                raise
            existing = queue.task(task_id)
            provenance = existing.get("extra", {}).get("orion", {})
            if provenance != task.get("extra", {}).get("orion", {}):
                raise RuntimeError(
                    f"Task {task_id} already exists with different "
                    "publication provenance"
                ) from exc
    return list(tasks)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m orion_decision.gha_publish")
    sub = parser.add_subparsers(dest="command", required=True)
    decision = sub.add_parser("decision")
    decision.add_argument("--event-file", type=Path)
    decision.add_argument("--github-action", required=True)
    decision.add_argument("--task-group", required=True)
    direct = sub.add_parser("schedule")
    direct.add_argument("--manifest-file", type=Path, required=True)
    direct.add_argument("--task-group", required=True)
    artifact = sub.add_parser("import-artifact")
    artifact.add_argument("--artifact-id", required=True)
    artifact.add_argument("--repository", required=True)
    artifact.add_argument("--filename", required=True)
    artifact.add_argument("--digest", default="")
    artifact.add_argument("--destination", type=Path, required=True)
    manifest_parser = sub.add_parser("manifest")
    manifest_parser.add_argument("--plan-file", type=Path, required=True)
    manifest_parser.add_argument("--output", type=Path, required=True)
    monitor = sub.add_parser("monitor")
    monitor.add_argument("--manifest-file", type=Path, required=True)
    monitor.add_argument("--timeout", type=float, default=3600)
    monitor.add_argument("--poll-interval", type=float, default=10)
    args = parser.parse_args()
    if args.command == "import-artifact":
        import_artifact(
            args.artifact_id,
            args.repository,
            args.filename,
            args.destination,
            digest=args.digest or None,
        )
        return
    if args.command == "manifest":
        _write_manifest(args.output, args.plan_file)
        return
    if args.command == "monitor":
        monitor_imports(
            json.loads(args.manifest_file.read_text()),
            timeout=args.timeout,
            poll_interval=args.poll_interval,
        )
        return
    if args.command == "decision":
        event = (
            json.loads(args.event_file.read_text())
            if args.event_file
            else json.loads(os.environ["GITHUB_EVENT"])
        )
        try:
            manifest = find_manifest_for_event(event, args.github_action)
        except RuntimeError as exc:
            if not str(exc).startswith("No eligible Orion GHA manifest found"):
                raise
            # A shared worker can claim the webhook decision while its GHA graph
            # is still running. The gated GHA publication job always ensures the
            # same deterministic import tasks after it has a complete manifest.
            print(f"Publication manifest is not ready; GHA will ensure imports: {exc}")
            return
    else:
        manifest = json.loads(args.manifest_file.read_text())
    expected = {
        "repository": manifest["repository"],
        "revision": manifest["revision"],
        "event": manifest["event"],
        "branch": manifest["branch"],
        "run_id": manifest["run_id"],
        "attempt": manifest["run_attempt"],
    }
    validate_manifest(manifest, **expected)
    create_tasks(manifest, args.task_group)


if __name__ == "__main__":
    main()
