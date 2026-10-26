# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Coordinate independently submitted publications and their GHA worker pool."""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import time
import urllib.error
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import ARTIFACTS_EXPIRE, DEADLINE, OWNER_EMAIL, PROVISIONER_ID, SOURCE_URL
from .gha_publish import (
    MARKER_ROUTE,
    WORKER,
    Taskcluster,
    _actions_artifacts,
    _github_json,
    _required_artifact_digest,
    _token,
    artifact_task_id,
    download_artifact_json,
    publication_rank,
    submit_tasks,
)

CLOSE_JOB = "Orion publication submissions complete"
SERVICE_ROUTE = "project.fuzzing.orion.gha.services"
GROUP_ROUTE = "project.fuzzing.orion.gha.groups"
TERMINAL = {"completed", "failed", "exception", "canceled"}


def identity(plan: dict[str, Any]) -> dict[str, Any]:
    """Bind publication metadata to one eligible workflow attempt."""
    if (
        not plan.get("publish")
        or plan.get("branch") != "master"
        or os.environ["GITHUB_REPOSITORY"] != "MozillaSecurity/orion"
    ):
        raise ValueError("Only Orion master publication runs may submit tasks")
    return {
        "repository": os.environ["GITHUB_REPOSITORY"],
        "revision": plan["revision"],
        "event": plan["event"],
        "branch": plan["branch"],
        "runId": os.environ["GITHUB_RUN_ID"],
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        "runNumber": int(os.environ["GITHUB_RUN_NUMBER"]),
    }


def metadata_task(
    data: dict[str, Any],
    group: str,
    name: str,
    route: str,
    *,
    dependencies: list[str] | None = None,
) -> dict[str, Any]:
    """Store small immutable publication metadata using ordinary TC artifacts."""
    now = datetime.now(timezone.utc)
    expires = (now + ARTIFACTS_EXPIRE).isoformat()
    return {
        "taskGroupId": group,
        "dependencies": dependencies or [],
        "created": now.isoformat(),
        "deadline": (now + DEADLINE).isoformat(),
        "expires": expires,
        "provisionerId": PROVISIONER_ID,
        "workerType": WORKER,
        "schedulerId": "taskcluster-github",
        "priority": "highest" if data.get("root") else "lowest",
        "routes": [f"index.{route}"],
        "payload": {
            "maxRunTime": 3600,
            "command": [
                [
                    "bash",
                    "-e",
                    "-c",
                    "mkdir -p orion-import && printf '%s\\n' "
                    + shlex.quote(json.dumps(data, sort_keys=True))
                    + " > orion-import/metadata.json",
                ]
            ],
            "artifacts": [
                {
                    "name": "public/orion-publication.json",
                    "type": "file",
                    "path": "orion-import/metadata.json",
                    "expires": expires,
                }
            ],
        },
        "scopes": ["queue:scheduler-id:taskcluster-github"],
        "metadata": {
            "name": name,
            "description": "Orion publication provenance",
            "owner": OWNER_EMAIL,
            "source": SOURCE_URL,
        },
        "extra": {
            "index": {
                "rank": publication_rank(data["runId"], data["runAttempt"]),
                "data": data,
            },
            "orion": data,
        },
    }


def bootstrap(plan: dict[str, Any], *, timeout: float = 4500) -> str:
    """Reuse the push decision group, or create a root for non-push runs."""
    data = identity(plan)
    require_workers()
    if plan["event"] != "push":
        group = artifact_task_id(data["runId"], 1, "decision")
        root_data = {**data, "runAttempt": "1", "root": True}
        submit_tasks(
            {
                group: metadata_task(
                    root_data,
                    group,
                    "Orion publication decision",
                    f"{GROUP_ROUTE}.run.{data['runId']}",
                )
            }
        )
        return group
    index = Taskcluster.get_service("index")
    queue = Taskcluster.get_service("queue")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            record = index.findTask(f"{GROUP_ROUTE}.rev.{plan['revision']}")
            task = queue.task(record["taskId"])
            root_data = task.get("extra", {}).get("index", {}).get("data", {})
            if (
                root_data.get("repository") != data["repository"]
                or root_data.get("revision") != data["revision"]
                or not root_data.get("root")
            ):
                raise ValueError("Publication group does not match this push")
            return record["taskId"]
        except Exception as exc:
            if getattr(exc, "status_code", None) != 404:
                raise
        time.sleep(5)
    raise TimeoutError("Taskcluster push decision did not establish its group")


def schedule_receipt(plan: dict[str, Any], service_name: str, group: str) -> str:
    """Record one fully published service without depending on peer services."""
    from .gha_plan import job_id
    from .git import GitRepo
    from .orion import ServiceHomebrew, ServiceMsys, Services, ServiceTestOnly

    data = identity(plan)
    require_workers()
    service = Services(GitRepo.from_existing(Path.cwd()))[service_name]
    if isinstance(service, ServiceTestOnly):
        raise ValueError("Test-only services do not have publication receipts")
    builds = {job_id("build", service_name, arch) for arch in service.archs}
    if not builds <= set(plan["selected_jobs"]):
        raise ValueError("A service receipt requires all architecture builds")
    images = {}
    if not isinstance(service, (ServiceHomebrew, ServiceMsys)):
        name = (
            f"orion-published-image-digests-{service_name}-"
            f"{data['runId']}-{data['runAttempt']}"
        )
        artifacts = _actions_artifacts(
            os.environ["GITHUB_TOKEN"], data["repository"], data["runId"]
        )
        artifact = next(
            (
                item
                for item in artifacts
                if item["name"] == name and not item.get("expired")
            ),
            None,
        )
        if artifact is None:
            raise ValueError(f"Docker publication metadata missing for {service_name}")
        images = download_artifact_json(
            artifact["id"],
            "published-images.json",
            data["repository"],
            digest=_required_artifact_digest(artifact),
            token=os.environ["GITHUB_TOKEN"],
        )
        publication = images.get(service_name, {})
        if publication.get("latest_published") is not True or set(
            publication.get("architectures", {})
        ) != set(service.archs):
            raise ValueError(f"Docker publication incomplete for {service_name}")
    dependencies = [
        artifact_task_id(data["runId"], data["runAttempt"], f"{service_name}-{arch}")
        for arch in sorted(service.archs)
    ]
    receipt_id = artifact_task_id(
        data["runId"], data["runAttempt"], f"receipt-{service_name}"
    )
    data.update({"service": service_name, "published_images": images})
    submit_tasks(
        {
            receipt_id: metadata_task(
                data,
                group,
                f"Orion publication {service_name}",
                f"{SERVICE_ROUTE}.{service_name}.master",
                dependencies=dependencies,
            )
        }
    )
    return receipt_id


def group_tasks(group: str, run_id: str, attempt: str, queue: Any) -> list[dict]:
    """Enumerate actual submitted tasks, including partially failed submissions."""
    tasks = []
    options: dict[str, str] = {}
    while True:
        page = queue.listTaskGroup(group, query=options)
        for item in page.get("tasks", []):
            data = item["task"].get("extra", {}).get("orion", {})
            if (
                str(data.get("runId")) == run_id
                and str(data.get("runAttempt")) == attempt
            ):
                tasks.append(item)
        token = page.get("continuationToken")
        if not token:
            return tasks
        options = {"continuationToken": token}


def close_submissions(plan: dict[str, Any], group: str, output: Path) -> None:
    """Close submissions after all producers finish, without gating any import."""
    from .gha_plan import job_id
    from .git import GitRepo
    from .orion import Services, ServiceTestOnly

    data = identity(plan)
    results = json.loads(os.environ["ORION_JOB_RESULTS"])
    failed = [
        name
        for name, item in results.items()
        if item["result"] in {"failure", "cancelled"}
    ]
    services = Services(GitRepo.from_existing(Path.cwd()))
    required = {"plan", "publication-bootstrap", "graph-result"}
    required.update(
        job_id("receipt", service.name)
        for service in services.values()
        if not isinstance(service, ServiceTestOnly)
        and any(
            job_id("build", service.name, arch) in plan["selected_jobs"]
            for arch in service.archs
        )
    )
    failed += sorted(
        name for name in required if results.get(name, {}).get("result") != "success"
    )
    expected = [
        artifact_task_id(data["runId"], data["runAttempt"], f"{service.name}-{arch}")
        for service in services.values()
        for arch in service.archs
        if results.get(job_id("index", service.name, arch), {}).get("result")
        == "success"
    ]
    expected += [
        artifact_task_id(data["runId"], data["runAttempt"], f"receipt-{service.name}")
        for service in services.values()
        if results.get(job_id("receipt", service.name), {}).get("result") == "success"
    ]
    try:
        if not failed and group:
            require_workers()
            dependencies = [
                artifact_task_id(data["runId"], data["runAttempt"], f"receipt-{s.name}")
                for s in services.values()
                if not isinstance(s, ServiceTestOnly)
                and any(
                    job_id("build", s.name, arch) in plan["selected_jobs"]
                    for arch in s.archs
                )
            ]
            marker = artifact_task_id(
                data["runId"], data["runAttempt"], "publication-marker"
            )
            submit_tasks(
                {
                    marker: metadata_task(
                        data,
                        group,
                        "Orion successful publication marker",
                        MARKER_ROUTE,
                        dependencies=dependencies,
                    )
                }
            )
            expected.append(marker)
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    **data,
                    "task_group": group,
                    "failed_jobs": sorted(set(failed)),
                    "task_ids": sorted(expected),
                }
            )
            + "\n"
        )
    if failed:
        raise RuntimeError(
            "Publication producers failed: " + ", ".join(sorted(set(failed)))
        )


def _attempt_jobs(
    repository: str,
    run_id: str,
    attempt: str,
    *,
    token: str | None = None,
) -> list[dict]:
    jobs = []
    page = 1
    while True:
        response = _github_json(
            f"https://api.github.com/repos/{repository}/actions/runs/{run_id}"
            f"/attempts/{attempt}/jobs?per_page=100&page={page}",
            token=token,
        )
        batch = response.get("jobs", [])
        jobs.extend(batch)
        if len(batch) < 100:
            return jobs
        page += 1


def require_workers() -> None:
    """Reject partial reruns that would submit work without this attempt's pool."""
    jobs = _attempt_jobs(
        os.environ["GITHUB_REPOSITORY"],
        os.environ["GITHUB_RUN_ID"],
        os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        token=os.environ["GITHUB_TOKEN"],
    )
    names = {"Taskcluster worker 1", "Taskcluster worker 2"}
    workers = [job for job in jobs if job["name"] in names]
    if {job["name"] for job in workers} != names or not any(
        job["status"] != "completed" for job in workers
    ):
        raise RuntimeError("This attempt has no active worker pool; re-run all jobs")


def _github_retry(operation: Callable[[], Any], deadline: float) -> Any:
    """Keep workers serving TC during transient GitHub API outages."""
    while True:
        try:
            return operation()
        except urllib.error.HTTPError as exc:
            headers: Any = exc.headers or {}
            rate_limited = exc.code == 403 and (
                headers.get("X-RateLimit-Remaining") == "0"
                or headers.get("Retry-After") is not None
            )
            if exc.code != 429 and exc.code < 500 and not rate_limited:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("GitHub API unavailable until worker-pool deadline")
        time.sleep(min(60, remaining))


def monitor_pool(
    plan: dict[str, Any],
    *,
    queue: Any | None = None,
    timeout: float = 16200,
    poll_interval: float = 60,
    worker: Any | None = None,
) -> None:
    """Keep serving until producers close and every submitted TC task settles."""
    data = identity(plan)
    queue = queue or Taskcluster.get_service("queue")
    deadline = time.monotonic() + timeout
    group = None
    closed = False
    control_error = None
    expected: set[str] = set()
    while time.monotonic() < deadline:
        if worker is not None and worker.poll() is not None:
            raise RuntimeError(f"Generic-worker exited early ({worker.returncode})")
        if not closed:
            jobs = _github_retry(
                lambda: _attempt_jobs(
                    data["repository"], data["runId"], data["runAttempt"]
                ),
                deadline,
            )
            close_job = next((job for job in jobs if job["name"] == CLOSE_JOB), None)
            closed = close_job is not None and close_job["status"] == "completed"
            if group is None or closed:
                artifacts = _github_retry(
                    lambda: _actions_artifacts(
                        _token(), data["repository"], data["runId"]
                    ),
                    deadline,
                )
                prefixes = [("group", "group.json")]
                if closed:
                    prefixes.append(("control", "publication-control.json"))
                for prefix, filename in prefixes:
                    name = (
                        f"orion-publication-{prefix}-"
                        f"{data['runId']}-{data['runAttempt']}"
                    )
                    artifact = next(
                        (
                            item
                            for item in artifacts
                            if item["name"] == name and not item.get("expired")
                        ),
                        None,
                    )
                    if artifact is None:
                        if prefix == "control":
                            control_error = "Publication control artifact is missing"
                        continue
                    try:
                        record = _github_retry(
                            lambda: download_artifact_json(
                                artifact["id"],
                                filename,
                                data["repository"],
                                digest=_required_artifact_digest(artifact),
                            ),
                            deadline,
                        )
                        if any(
                            str(record.get(key)) != str(data[key])
                            for key in ("repository", "revision", "runId", "runAttempt")
                        ):
                            raise ValueError(
                                "Worker-pool control belongs to another attempt"
                            )
                        candidate = record.get("task_group")
                        if candidate:
                            if group is not None and group != candidate:
                                raise ValueError(
                                    "Publication group changed during this run"
                                )
                            group = candidate
                        if prefix == "control":
                            expected.update(record.get("task_ids", []))
                    except (ValueError, KeyError, json.JSONDecodeError) as exc:
                        control_error = str(exc)
        if closed:
            if not group:
                route = (
                    f"{GROUP_ROUTE}.rev.{data['revision']}"
                    if plan["event"] == "push"
                    else f"{GROUP_ROUTE}.run.{data['runId']}"
                )
                try:
                    group = Taskcluster.get_service("index").findTask(route)["taskId"]
                except Exception as exc:
                    if getattr(exc, "status_code", None) != 404:
                        raise
                    raise RuntimeError(
                        control_error or "Publication group was not created"
                    ) from exc
            tasks = group_tasks(group, data["runId"], data["runAttempt"], queue)
            found = {item["status"]["taskId"] for item in tasks}
            for task_id in expected - found:
                try:
                    status = queue.status(task_id)
                    tasks.append({"status": status.get("status", status)})
                except Exception as exc:
                    if getattr(exc, "status_code", None) != 404:
                        raise
                    control_error = f"Expected publication task is missing: {task_id}"
            pending = [
                item for item in tasks if item["status"]["state"] not in TERMINAL
            ]
            if not pending:
                failed = [
                    item["status"]["taskId"]
                    for item in tasks
                    if item["status"]["state"] != "completed"
                ]
                if control_error or failed:
                    raise RuntimeError(
                        control_error or "TC imports failed: " + ", ".join(failed)
                    )
                return
        time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
    raise TimeoutError("Timed out draining Taskcluster publication graph")


def run_worker_pool(plan: dict[str, Any], timeout: float) -> None:
    """Run one pool member with a private token file and drain it on all exits."""
    worker = subprocess.Popen([".github/scripts/start-worker.sh"])
    try:
        monitor_pool(plan, timeout=timeout, worker=worker)
    finally:
        if worker.poll() is None:
            worker.send_signal(signal.SIGUSR1)
        try:
            result = worker.wait(timeout=3800)
        except subprocess.TimeoutExpired:
            worker.terminate()
            worker.wait(timeout=30)
            raise RuntimeError("Generic-worker exceeded its drain deadline") from None
        if result:
            raise RuntimeError(f"Generic-worker exited with status {result}")
