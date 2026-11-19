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
    SCHEDULER_ID,
    SOURCE_URL,
    Taskcluster,
)
from .git import GitRepo

QUEUE = "orion-gha-publish"
WORKER = "orion-gha-publish"
WORKER_CLIENT = "project/fuzzing/ci-worker-orion-gha"
MARKER_ROUTE = "project.fuzzing.orion.gha.main"
MANIFEST_SCHEMA = 2
# Taskcluster stores ranks as signed 32-bit integers. The direct publisher uses
# the maximum to supersede legacy writers and compares full ordering metadata.
DIRECT_INDEX_RANK = 2_147_483_647


def artifact_task_id(run_id: str, attempt: str | int, key: str) -> str:
    """Return a stable Taskcluster ID for one artifact in one workflow attempt."""
    digest = hashlib.sha256(f"{run_id}:{attempt}:{key}".encode()).digest()[:16]
    import base64

    tc_uuid = uuid.UUID(bytes=digest, version=4)
    return base64.urlsafe_b64encode(tc_uuid.bytes).decode().rstrip("=")


def publication_rank(
    run_number: str | int, attempt: str | int, landing_order: int | None = None
) -> int:
    """Use the reserved direct-write rank or the legacy automatic-route rank."""
    if landing_order is not None:
        return DIRECT_INDEX_RANK
    attempt_number = int(attempt)
    if not 1 <= attempt_number <= 99:
        raise ValueError("GitHub Actions run attempt must be between 1 and 99")
    return int(run_number) * 100 + attempt_number


def publication_order(
    landing_order: int, run_number: str | int, attempt: str | int
) -> tuple[int, int, int]:
    """Order main revisions first, then workflow runs and attempts of that revision."""
    order = (landing_order, int(run_number), int(attempt))
    if min(order) < 1:
        raise ValueError(f"Publication order must contain positive numbers: {order}")
    return order


def main_positions(repo: GitRepo) -> dict[str, int]:
    """Read main's first-parent history from a full checkout."""
    return {
        revision: number
        for number, revision in enumerate(
            repo.git(
                "rev-list", "--reverse", "--first-parent", "refs/remotes/origin/main"
            ).splitlines(),
            1,
        )
    }


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
    from .gha_plan import job_id

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
    selected = set(manifest.get("selected_jobs", []))
    successful = set(manifest.get("successful_jobs", []))
    if not successful <= selected:
        raise ValueError("Publication manifest reports unselected successful jobs")
    expected_builds = {job for job in successful if job.startswith("build_")}
    artifact_builds = {
        job_id("build", artifact["service"], artifact["arch"])
        for artifact in manifest["artifacts"]
    }
    if artifact_builds != expected_builds:
        raise ValueError(
            "Publication manifest artifacts do not match successful build jobs"
        )
    gates = manifest.get("gates", {})
    docker_latest = gates.get("docker_latest")
    if docker_latest not in {"success", "failure", "skipped", "not-required"}:
        raise ValueError("Publication manifest has an invalid Docker publication gate")
    if manifest.get("selected_docker_jobs") and docker_latest == "not-required":
        raise ValueError("Selected Docker builds require a Docker publication result")
    if not manifest.get("selected_docker_jobs") and docker_latest != "not-required":
        raise ValueError("Docker publication gate must be not-required")
    complete = successful == selected and docker_latest in {"success", "not-required"}
    if manifest.get("complete") is not complete:
        raise ValueError("Publication manifest has an inconsistent completion status")
    expected_selected_gate = "success" if successful == selected else "partial"
    if gates.get("selected_jobs") != expected_selected_gate:
        raise ValueError("Publication manifest has an inconsistent selected-jobs gate")


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
    rank = publication_rank(
        manifest["run_number"], manifest["run_attempt"], manifest.get("landing_order")
    )
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
        provenance = {
            "revision": manifest["revision"],
            "repository": manifest["repository"],
            "runId": str(manifest["run_id"]),
            "runAttempt": str(manifest["run_attempt"]),
            "runNumber": int(manifest["run_number"]),
            "artifactId": str(item["artifact_id"]),
            "artifactKey": item["key"],
            "artifactDigest": item.get("digest"),
            "publicationKind": "import",
        }
        routes = _artifact_indexes(manifest, item)
        if "landing_order" in manifest:
            provenance["landingOrder"] = manifest["landing_order"]
            provenance["indexPaths"] = [
                route.removeprefix("index.") for route in routes
            ]
            routes = []
        if manifest.get("artifact_only"):
            provenance["independentPublication"] = True
        elif item["kind"] == "docker":
            provenance["dockerLatestPublished"] = bool(
                manifest.get("published_images", {})
                .get(item["service"], {})
                .get("latest_published")
            )
        task_name = f"Orion import {item['service']} {item.get('arch', '')}".strip()
        task = {
            "taskGroupId": task_group,
            "dependencies": [],
            "created": now.isoformat(),
            "deadline": deadline,
            "expires": expires,
            "provisionerId": PROVISIONER_ID,
            "workerType": WORKER,
            "schedulerId": SCHEDULER_ID,
            "routes": routes,
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
            "scopes": [],
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

    if manifest["complete"] and not manifest.get("artifact_only"):
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
        routes = [f"index.{MARKER_ROUTE}"]
        if "landing_order" in manifest:
            marker["landing_order"] = manifest["landing_order"]
            marker["indexPaths"] = [MARKER_ROUTE]
            routes = []
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
            "schedulerId": SCHEDULER_ID,
            "routes": routes,
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
            "scopes": [],
            "metadata": {
                "name": "Orion successful publication marker",
                "description": "Marks a fully imported Orion GHA publication baseline",
                "owner": OWNER_EMAIL,
                "source": SOURCE_URL,
            },
            "extra": {
                "index": {
                    "rank": rank,
                    "data": marker,
                },
                "orion": marker,
            },
        }
    return tasks


def expected_import_task_ids(manifest: dict[str, Any]) -> list[str]:
    """Return IDs for successful artifact imports and any complete-run marker."""
    ids = [
        artifact_task_id(
            str(manifest["run_id"]), manifest["run_attempt"], str(item["key"])
        )
        for item in manifest["artifacts"]
    ]
    if manifest["complete"] and not manifest.get("artifact_only"):
        ids.append(
            artifact_task_id(
                str(manifest["run_id"]),
                manifest["run_attempt"],
                "publication-marker",
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


def select_build_artifact(
    artifacts: list[dict[str, Any]],
    service: str,
    arch: str,
    attempt: str | int,
) -> dict[str, Any] | None:
    """Choose the newest live exact service/architecture artifact up to attempt."""
    prefix = f"orion-build-{service}-{arch}-"
    return select_attempt_artifact(artifacts, prefix, attempt)


def select_attempt_artifact(
    artifacts: list[dict[str, Any]], prefix: str, attempt: str | int
) -> dict[str, Any] | None:
    """Choose the newest live artifact with an exact numeric attempt suffix."""
    current = int(attempt)
    if current < 1:
        raise ValueError("GitHub Actions run attempt must be positive")
    candidates: list[tuple[int, dict[str, Any]]] = []
    for artifact in artifacts:
        name = artifact.get("name")
        if not isinstance(name, str) or not name.startswith(prefix):
            continue
        suffix = name.removeprefix(prefix)
        if not re.fullmatch(r"[1-9][0-9]*", suffix):
            continue
        producer_attempt = int(suffix)
        if producer_attempt <= current and not artifact.get("expired"):
            candidates.append((producer_attempt, artifact))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate[0])[1]


def _publication_run(data: dict[str, Any]) -> tuple[int, int]:
    """Return a same-revision ordering key, with a fallback for legacy metadata."""
    return int(data.get("runNumber") or data["runId"]), int(data.get("runAttempt", 1))


def publication_state(
    *,
    index: Any | None = None,
    queue: Any | None = None,
    now: datetime | None = None,
    services: Any | None = None,
) -> dict[str, Any]:
    """Read global and per-service publication baselines plus expiring archives."""
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
    service_revisions: dict[str, str] = {}
    service_runs: dict[str, tuple[int, int]] = {}
    docker_latest_failed: list[str] = []
    incomplete_services: list[str] = []
    for service in services.values():
        if isinstance(service, ServiceTestOnly):
            continue
        native = isinstance(service, (ServiceHomebrew, ServiceMsys))
        archs = service.archs
        archive_tasks: dict[str, str] = {}
        revisions: list[str | None] = []
        publication_runs: list[tuple[int, int] | None] = []
        service_expired = False
        independent = False
        for arch in archs:
            route = f"project.fuzzing.orion.{service.name}"
            if not native:
                route += f".{arch}"
            route += ".main"
            try:
                indexed = index.findTask(route)
                task_id = indexed["taskId"]
                task = queue.task(task_id)
                task_expires = isoparse(task["expires"])
                status = queue.status(task_id)
                status = status.get("status", status)
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
                    service_expired = True
                data = indexed.get("data") or task.get("extra", {}).get(
                    "index", {}
                ).get("data", {})
                completed = (
                    status.get("state") == "completed"
                    and status.get("runs", [{}])[-1].get("state") == "completed"
                    and artifact is not None
                    and data.get("repository") == "MozillaSecurity/orion"
                    and isinstance(data.get("revision"), str)
                    and re.fullmatch(r"[0-9a-f]{40}", data["revision"])
                )
                independent |= bool(data.get("independentPublication"))
                if (
                    completed
                    and not native
                    and not data.get("independentPublication")
                    and data.get("dockerLatestPublished") is False
                ):
                    docker_latest_failed.append(service.name)
                if completed and (
                    data.get("independentPublication")
                    or native
                    or data.get("dockerLatestPublished") is True
                ):
                    revisions.append(data["revision"])
                    archive_tasks[arch] = task_id
                    try:
                        publication_runs.append(_publication_run(data))
                    except (KeyError, TypeError, ValueError):
                        publication_runs.append(None)
                else:
                    revisions.append(None)
                    publication_runs.append(None)
            except Exception as exc:
                if getattr(exc, "status_code", None) == 404:
                    service_expired = True
                    revisions.append(None)
                    continue
                raise
        if service_expired:
            expired.append(service.name)
        if independent:
            from .gha_pool import SERVICE_ROUTE

            try:
                record = index.findTask(f"{SERVICE_ROUTE}.{service.name}.main")
                receipt_task = queue.task(record["taskId"])
                status = queue.status(record["taskId"])
                status = status.get("status", status)
                receipt = record.get("data") or receipt_task.get("extra", {}).get(
                    "index", {}
                ).get("data", {})
                if (
                    status.get("state") != "completed"
                    or status.get("runs", [{}])[-1].get("state") != "completed"
                    or receipt.get("repository") != "MozillaSecurity/orion"
                    or receipt.get("service") != service.name
                    or not re.fullmatch(
                        r"[0-9a-f]{40}", str(receipt.get("revision", ""))
                    )
                ):
                    incomplete_services.append(service.name)
                    continue
                receipt_run = _publication_run(receipt)
                service_revisions[service.name] = receipt["revision"]
                service_runs[service.name] = receipt_run
                if "importTaskIds" in receipt:
                    matching_imports = receipt[
                        "importTaskIds"
                    ] == archive_tasks and set(archive_tasks.values()) == set(
                        receipt_task.get("dependencies", [])
                    )
                else:
                    matching_imports = all(
                        run == receipt_run for run in publication_runs
                    )
                if (
                    len(revisions) != len(archs)
                    or any(
                        rev is None or rev != receipt["revision"] for rev in revisions
                    )
                    or not matching_imports
                ):
                    incomplete_services.append(service.name)
            except Exception as exc:
                if getattr(exc, "status_code", None) != 404:
                    raise
                incomplete_services.append(service.name)
            continue
        if len(revisions) == len(archs) and revisions and None not in revisions:
            service_revision = revisions[0]
            if isinstance(service_revision, str) and all(
                revision == service_revision for revision in revisions
            ):
                service_revisions[service.name] = service_revision
                valid_runs = [run for run in publication_runs if run is not None]
                if valid_runs and len(valid_runs) == len(publication_runs):
                    if len(set(valid_runs)) == 1:
                        service_runs[service.name] = valid_runs[0]
                    else:
                        incomplete_services.append(service.name)
                elif valid_runs:
                    incomplete_services.append(service.name)
            else:
                incomplete_services.append(service.name)
    return {
        "base_revision": baseline,
        "expired_services": sorted(set(expired)),
        "service_revisions": service_revisions,
        "service_runs": service_runs,
        "docker_latest_failed": sorted(set(docker_latest_failed)),
        "incomplete_services": sorted(set(incomplete_services)),
    }


def create_manifest(
    plan: dict[str, Any],
    *,
    token: str,
    service_name: str | None = None,
    arch: str | None = None,
    artifact_only: bool = False,
) -> dict[str, Any]:
    """Bind selected successful GHA build artifacts to this exact workflow attempt."""
    from .gha_plan import job_id
    from .git import GitRepo
    from .orion import ServiceHomebrew, ServiceMsys, Services, ServiceTestOnly

    repo = Path.cwd()
    if artifact_only:
        from .gha_pool import require_workers

        require_workers()
    services = Services(GitRepo.from_existing(repo))
    repository = os.environ["GITHUB_REPOSITORY"]
    revision = plan["revision"]
    run_id = str(os.environ["GITHUB_RUN_ID"])
    attempt = str(os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
    artifacts = _actions_artifacts(token, repository, run_id)
    selected = set(plan.get("selected_jobs", []))
    if artifact_only:
        if service_name is None or arch is None:
            raise ValueError("Artifact publication requires a service and architecture")
        selected &= {job_id("build", service_name, arch)}
        if not selected:
            raise ValueError("Artifact build was not selected in this plan")
    try:
        job_results = json.loads(os.environ["ORION_JOB_RESULTS"])
    except (KeyError, json.JSONDecodeError) as exc:
        raise ValueError("GitHub job results are required for publication") from exc
    successful = {
        job for job in selected if job_results.get(job, {}).get("result") == "success"
    }
    if artifact_only and successful != selected:
        raise ValueError("Artifact build did not succeed")
    docker_latest = (
        job_results.get("publish-docker", {}).get("result", "skipped")
        if plan.get("selected_docker_jobs") and not artifact_only
        else "not-required"
    )
    entries: list[dict[str, Any]] = []
    for service in sorted(services.values(), key=lambda item: item.name):
        if isinstance(service, ServiceTestOnly):
            continue
        for arch in service.archs:
            build_job = job_id("build", service.name, arch)
            if build_job not in successful:
                continue
            artifact = select_build_artifact(artifacts, service.name, arch, attempt)
            if artifact is None:
                raise ValueError(
                    f"No live build artifact for {service.name}/{arch} exists "
                    f"from this run at or before attempt {attempt}"
                )
            name = artifact["name"]
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
    if plan.get("selected_docker_jobs") and not artifact_only:
        digest_artifact = select_attempt_artifact(
            artifacts, f"orion-published-image-digests-{run_id}-", attempt
        )
        if digest_artifact is not None:
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
        **({"landing_order": plan["landing_order"]} if "landing_order" in plan else {}),
        "event": os.environ["GITHUB_EVENT_NAME"],
        "branch": os.environ["GITHUB_REF_NAME"],
        "workflow": "orion.yml",
        "selected_jobs": sorted(selected),
        "selected_docker_jobs": []
        if artifact_only
        else sorted(plan.get("selected_docker_jobs", [])),
        "successful_jobs": sorted(successful),
        "publish": bool(plan.get("publish"))
        and os.environ["GITHUB_REF_NAME"] == "main",
        "complete": successful == selected
        and docker_latest in {"success", "not-required"},
        "gates": {
            "selected_jobs": "success" if successful == selected else "partial",
            "docker_latest": docker_latest,
        },
        "artifacts": entries,
        "published_images": published_images,
        "artifact_only": artifact_only,
    }


def _write_manifest(
    path: Path,
    plan_path: Path,
    *,
    service_name: str | None = None,
    arch: str | None = None,
    artifact_only: bool = False,
) -> None:
    plan = json.loads(plan_path.read_text())
    token = os.environ["GITHUB_TOKEN"]
    manifest = create_manifest(
        plan,
        token=token,
        service_name=service_name,
        arch=arch,
        artifact_only=artifact_only,
    )
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
    monitor_tasks(
        expected_import_task_ids(manifest),
        queue=queue,
        timeout=timeout,
        poll_interval=poll_interval,
    )


def monitor_tasks(
    task_ids: list[str],
    *,
    queue: Any | None = None,
    timeout: float = 3600,
    poll_interval: float = 10,
) -> None:
    """Wait for exact Taskcluster producers before making their index paths live."""
    queue = queue or Taskcluster.get_service("queue")
    deadline = time.monotonic() + timeout
    pending = set(task_ids)
    failures: dict[str, str] = {}
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
                failures[task_id] = state
                pending.remove(task_id)
                continue
            if state == "completed":
                if status.get("runs", [{}])[-1].get("state") != "completed":
                    failures[task_id] = "did not complete"
                pending.remove(task_id)
        if pending:
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
    if pending:
        raise TimeoutError(
            "Timed out waiting for Taskcluster publication tasks: "
            + ", ".join(sorted(pending))
            + (
                "; failed tasks: "
                + ", ".join(
                    f"{task_id} ({state})"
                    for task_id, state in sorted(failures.items())
                )
                if failures
                else ""
            )
        )
    if failures:
        raise RuntimeError(
            "Taskcluster publication tasks failed: "
            + ", ".join(
                f"{task_id} ended {state}"
                for task_id, state in sorted(failures.items())
            )
        )


def _indexed_order(
    data: dict[str, Any], positions: dict[str, int], repository: str
) -> tuple[int, int, int]:
    """Resolve ordering for current and legacy Orion index entries."""
    if data.get("repository") != repository or "revision" not in data:
        return (0, 0, 0)
    revision = data["revision"]
    position = positions.get(revision)
    if position is None:
        raise ValueError(
            f"Indexed revision {revision!r} is not on main's first-parent history"
        )
    declared_position = data.get("landingOrder", data.get("landing_order", position))
    if declared_position != position:
        raise ValueError(
            f"Indexed revision {revision!r} has the wrong main landing order"
        )
    run_number = data.get("runNumber", data.get("run_number"))
    attempt = data.get("runAttempt", data.get("run_attempt", 1))
    return (
        publication_order(position, run_number, attempt)
        if run_number
        else (position, 0, 0)
    )


def promote_index(repo: GitRepo, task_id: str) -> None:
    """Index a completed producer under the GitHub publication lock."""
    queue = Taskcluster.get_service("queue")
    index = Taskcluster.get_service("index")
    task = queue.task(task_id)
    status = queue.status(task_id)["status"]
    if status["state"] != "completed" or status["runs"][-1]["state"] != "completed":
        raise ValueError(f"Task {task_id} did not complete successfully")
    provenance = task["extra"]["index"]["data"]
    paths = provenance["indexPaths"]
    repository = os.environ["GITHUB_REPOSITORY"]
    if provenance["repository"] != repository or not paths:
        raise ValueError(f"Task {task_id} has no matching publication paths")
    positions = main_positions(repo)
    order = _indexed_order(provenance, positions, repository)
    for path in paths:
        try:
            previous = index.findTask(path)
        except TaskclusterFailure as exc:
            if exc.status_code != 404:
                raise
        else:
            if _indexed_order(previous["data"], positions, repository) >= order:
                print(f"FXCI path {path} already has this or a newer publication")
                continue
        indexed = index.insertTask(
            path,
            {
                "taskId": task_id,
                "rank": DIRECT_INDEX_RANK,
                "data": provenance,
                "expires": task["expires"],
            },
        )
        if indexed["taskId"] != task_id:
            raise RuntimeError(f"FXCI did not index {task_id} at {path}")


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


def _github_json(url: str, *, token: str | None = None) -> dict[str, Any]:
    request = _github_request(url, token or _token())
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def download_artifact_json(
    artifact_id: str | int,
    filename: str,
    repository: str | None = None,
    digest: str | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    """Download one exact GitHub artifact ID, then read the named ZIP member."""
    repository = repository or os.environ.get("GITHUB_REPOSITORY")
    if not repository:
        raise RuntimeError("GITHUB_REPOSITORY is required")
    with TemporaryDirectory(prefix="orion-gha-artifact-") as tmp:
        path = Path(tmp) / "artifact.zip"
        _download_artifact_zip(
            artifact_id, repository, path, digest=digest, token=token
        )
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
    now = datetime.now(timezone.utc)
    tasks = build_import_tasks(manifest, task_group, now)
    return submit_tasks(tasks)


def submit_tasks(tasks: dict[str, dict[str, Any]]) -> list[str]:
    """Insert tasks idempotently without allowing a retry to change their group."""
    queue = Taskcluster.get_service("queue")
    for task_id, task in tasks.items():
        try:
            queue.createTask(task_id, task)
        except TaskclusterFailure as exc:
            if getattr(exc, "status_code", None) not in {409, 412}:
                raise
            existing = queue.task(task_id)
            provenance = existing.get("extra", {}).get("orion", {})
            if (
                provenance != task.get("extra", {}).get("orion", {})
                or existing.get("taskGroupId") != task["taskGroupId"]
                or existing.get("dependencies", []) != task.get("dependencies", [])
            ):
                raise RuntimeError(
                    f"Task {task_id} already exists with different "
                    "publication provenance"
                ) from exc
    return list(tasks)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m orion_decision.gha_publish")
    sub = parser.add_subparsers(dest="command", required=True)
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
    manifest_parser.add_argument("--service")
    manifest_parser.add_argument("--arch")
    manifest_parser.add_argument("--artifact-only", action="store_true")
    for name in ("bootstrap", "receipt", "close", "worker-pool"):
        command = sub.add_parser(name)
        command.add_argument("--plan-file", type=Path, required=True)
        if name in {"receipt", "close"}:
            command.add_argument("--task-group", required=True)
        if name == "receipt":
            command.add_argument("--service", required=True)
        if name in {"bootstrap", "close"}:
            command.add_argument("--output", type=Path, required=True)
        if name == "worker-pool":
            command.add_argument("--timeout", type=float, default=16200)
    monitor = sub.add_parser("monitor")
    monitor.add_argument("--manifest-file", type=Path, required=True)
    monitor.add_argument("--timeout", type=float, default=3600)
    monitor.add_argument("--poll-interval", type=float, default=10)
    wait_task = sub.add_parser("wait-task")
    wait_task.add_argument("--task-id", required=True)
    wait_task.add_argument("--timeout", type=float, default=3600)
    promote = sub.add_parser("promote-index")
    promote.add_argument("--task-id", required=True)
    args = parser.parse_args()
    if args.command == "wait-task":
        monitor_tasks([args.task_id], timeout=args.timeout)
        return
    if args.command == "promote-index":
        promote_index(GitRepo.from_existing(Path.cwd()), args.task_id)
        return
    if args.command in {"bootstrap", "receipt", "close", "worker-pool"}:
        from .gha_pool import (
            bootstrap,
            close_submissions,
            identity,
            run_worker_pool,
            schedule_receipt,
        )

        plan = json.loads(args.plan_file.read_text())
        if args.command == "bootstrap":
            group = bootstrap(plan)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps({**identity(plan), "task_group": group}) + "\n"
            )
            print(group)
        elif args.command == "receipt":
            receipt = schedule_receipt(plan, args.service, args.task_group)
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
                if receipt:
                    output.write(f"receipt_status=submitted\ntask_id={receipt}\n")
                else:
                    output.write("receipt_status=superseded\n")
        elif args.command == "close":
            marker = close_submissions(plan, args.task_group, args.output)
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
                output.write(f"marker_expected={str(marker is not None).lower()}\n")
                if marker:
                    output.write(f"task_id={marker}\n")
        else:
            run_worker_pool(plan, args.timeout)
        return
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
        _write_manifest(
            args.output,
            args.plan_file,
            service_name=args.service,
            arch=args.arch,
            artifact_only=args.artifact_only,
        )
        return
    if args.command == "monitor":
        monitor_imports(
            json.loads(args.manifest_file.read_text()),
            timeout=args.timeout,
            poll_interval=args.poll_interval,
        )
        return
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
    task_ids = create_tasks(manifest, args.task_group)
    if manifest.get("artifact_only") and "GITHUB_OUTPUT" in os.environ:
        (task_id,) = task_ids
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
            output.write(f"task_id={task_id}\n")


if __name__ == "__main__":
    main()
