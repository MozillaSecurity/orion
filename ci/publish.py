#!/usr/bin/env python3
"""Publish trusted GitHub build outputs to Docker Hub and Taskcluster.

This is intended for a protected GitHub Actions job.  It only accepts push,
schedule, or manual dispatch events targeting ``main`` and requires Taskcluster
and Docker Hub credentials in its environment.

Taskcluster uses its supported ``createTask`` -> ``claimWork`` -> ``createArtifact``
and ``finishArtifact`` -> ``reportCompleted`` lifecycle. Claims are renewed while
uploads run. Artifacts use the current object storage API and the Taskcluster Python
client's streaming upload helper. The input plan follows the build planner schema:

    {"head": "<full sha>", "services": {"name": {"kind": "docker"|"msys",
      "archs": ["amd64", "arm64"]}}}

Docker inputs are ``<artifact-dir>/<service>/<service>-<arch>.tar.zst``.  MSYS input
is ``<artifact-dir>/<service>/msys2.tar.bz2``.  Docker archives must contain
``docker.io/mozillasecurity/<service>:latest-<arch>`` as produced by the build job.

The Taskcluster client needs a narrowly scoped client with:

* ``queue:create-task:highest:proj-fuzzing/gh-pub-*``
* ``queue:claim-work:proj-fuzzing/gh-pub-*``
* ``queue:worker-id:github-actions/*``
* ``queue:create-artifact:public/*`` (as task scope, and on the client to create it)
* ``assume:worker-id:github-actions/pub-*`` (as task scope and on the client)
* ``queue:scheduler-id:github-actions``
* ``index:insert-task:project.fuzzing.orion.*``

The creator must also satisfy every task scope.  In particular, worker claims
receive the task scopes plus the claim scope.  The exact scope names should be
installed in the Firefox CI Taskcluster client/role and checked against that
deployment's current scope configuration before enabling the workflow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

LOG = logging.getLogger("orion-publish")
UTC = timezone.utc
TC_ROOT_DEFAULT = "https://firefox-ci-tc.services.mozilla.com"
PROVISIONER = "proj-fuzzing"
SCHEDULER = "github-actions"
IMAGE_NAMESPACE = "mozillasecurity"
ARTIFACT_TTL_DAYS = 365
CLAIM_REFRESH_SECONDS = 180
CLAIM_POLL_ATTEMPTS = 5
CLAIM_POLL_DELAY_SECONDS = 1
SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")


class PublishError(RuntimeError):
    """An invalid input or failed publication step."""


def require_trusted_main(env: dict[str, str] | None = None) -> None:
    """Refuse to publish except from an allowed event targeting main."""
    env = os.environ if env is None else env
    if (
        env.get("GITHUB_EVENT_NAME") not in {"push", "schedule", "workflow_dispatch"}
        or env.get("GITHUB_REF") != "refs/heads/main"
    ):
        raise PublishError("publishing is permitted only for main branch events")


def load_plan(path: Path) -> dict[str, Any]:
    """Read and minimally validate the planner output."""
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishError(f"cannot read build plan {path}: {exc}") from exc
    if not isinstance(plan, dict) or not isinstance(plan.get("services"), dict):
        raise PublishError("plan must contain a services object")
    head = plan.get("head")
    if not isinstance(head, str) or not SHA_RE.fullmatch(head):
        raise PublishError("plan head must be a full lowercase Git commit SHA")
    return plan


def _run(*args: str, input_text: str | None = None) -> str:
    """Run a publisher command, raising a useful error on failure."""
    LOG.info("Running %s", args[0])
    result = subprocess.run(
        args, check=False, text=True, input=input_text, capture_output=True
    )
    if result.returncode:
        raise PublishError(f"{args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def _date(value: datetime) -> str:
    return (
        value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def _client_options(
    root_url: str,
    client_id: str | dict[str, Any],
    access_token: str | None = None,
    certificate: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(client_id, dict):
        credentials = dict(client_id)
    else:
        credentials = {"clientId": client_id, "accessToken": access_token}
        if certificate is not None:
            credentials["certificate"] = certificate
    return {
        "rootUrl": root_url,
        "credentials": credentials,
        "maxRetries": 5,
    }


@dataclass
class TaskRun:
    task_id: str
    run_id: str
    task: dict[str, Any]
    queue: Any
    initial_credentials: dict[str, str]


class ClaimLease:
    """Renew a task claim and expose its most recent temporary credentials."""

    def __init__(self, root_url: str, run: TaskRun, taskcluster: Any) -> None:
        self.root_url = root_url
        self.run = run
        self.taskcluster = taskcluster
        self._credentials = run.initial_credentials
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._failure: BaseException | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.wait(CLAIM_REFRESH_SECONDS):
            try:
                queue = self.taskcluster.Queue(
                    _client_options(
                        self.root_url,
                        self._credentials,
                    )
                )
                response = queue.reclaimTask(self.run.task_id, self.run.run_id)
                with self._lock:
                    self._credentials = response["credentials"]
            except BaseException as exc:  # propagated in the publisher thread
                self._failure = exc
                self._stop.set()

    def queue(self) -> Any:
        if self._failure:
            raise PublishError(f"Taskcluster claim renewal failed: {self._failure}")
        with self._lock:
            credentials = dict(self._credentials)
        return self.taskcluster.Queue(_client_options(self.root_url, credentials))


class Publisher:
    """Taskcluster and registry operations, injectable for lifecycle tests."""

    def __init__(
        self,
        *,
        taskcluster: Any,
        upload_from_file: Any,
        env: dict[str, str],
        command: Any = _run,
        now: Any = datetime.now,
        sleep: Any = time.sleep,
    ) -> None:
        self.taskcluster = taskcluster
        self.upload_from_file = upload_from_file
        self.env = env
        self.command = command
        self.now = now
        self.sleep = sleep
        self.root_url = env.get("TASKCLUSTER_ROOT_URL", TC_ROOT_DEFAULT).rstrip("/")
        self.base_options = _client_options(
            self.root_url,
            self._required("TASKCLUSTER_CLIENT_ID"),
            self._required("TASKCLUSTER_ACCESS_TOKEN"),
        )
        self.queue = taskcluster.Queue(self.base_options)
        self.index = taskcluster.Index(self.base_options)
        run_number = int(env.get("GITHUB_RUN_NUMBER", "0"))
        run_attempt = int(env.get("GITHUB_RUN_ATTEMPT", "1"))
        self.rank = run_number * 1000 + run_attempt if run_number else int(time.time())
        self.run_id = (
            f"{env.get('GITHUB_RUN_ID', str(int(time.time())))}-"
            f"{env.get('GITHUB_RUN_ATTEMPT', '1')}"
        )
        self.worker_group = "github-actions"

    def _required(self, key: str) -> str:
        value = self.env.get(key)
        if not value:
            raise PublishError(f"required environment variable {key} is missing")
        return value

    def _taskcluster_task(
        self, task_id: str, worker_type: str, worker_id: str
    ) -> dict[str, Any]:
        created = self.now(UTC)
        deadline = created + timedelta(hours=3)
        expires = created + timedelta(days=ARTIFACT_TTL_DAYS + 1)
        return {
            "taskGroupId": task_id,
            "dependencies": [],
            "created": _date(created),
            "deadline": _date(deadline),
            "expires": _date(expires),
            "provisionerId": PROVISIONER,
            "schedulerId": SCHEDULER,
            "workerType": worker_type,
            "priority": "highest",
            "payload": {},
            "scopes": [
                "queue:create-artifact:public/*",
                f"assume:worker-id:{self.worker_group}/{worker_id}",
            ],
            "metadata": {
                "description": "Publish artifacts produced by GitHub Actions",
                "name": "Orion GitHub publication",
                "owner": "orion-maintainers@mozilla.com",
                "source": "https://github.com/MozillaSecurity/orion",
            },
        }

    def _worker_type(self, label: str, task_id: str) -> str:
        # Unique task queue per artifact task prevents claiming unrelated work.
        identity = f"{self.run_id}:{label}:{task_id}".encode()
        return "gh-pub-" + hashlib.sha256(identity).hexdigest()[:16]

    def _create_and_claim(self, label: str) -> tuple[TaskRun, ClaimLease]:
        task_id = self.taskcluster.slugId()
        worker_type = self._worker_type(label, task_id)
        worker_id = (
            f"pub-{self.run_id[-20:]}-{hashlib.sha1(label.encode()).hexdigest()[:8]}"
        )
        task = self._taskcluster_task(task_id, worker_type, worker_id)
        self.queue.createTask(task_id, task)
        claim = None
        for attempt in range(CLAIM_POLL_ATTEMPTS):
            claims = self.queue.claimWork(
                f"{PROVISIONER}/{worker_type}",
                {
                    "tasks": 1,
                    "workerGroup": self.worker_group,
                    "workerId": worker_id,
                },
            ).get("tasks", [])
            claim = next(
                (
                    item
                    for item in claims
                    if item.get("status", {}).get("taskId") == task_id
                ),
                None,
            )
            if claim is not None:
                break
            if attempt + 1 < CLAIM_POLL_ATTEMPTS:
                self.sleep(CLAIM_POLL_DELAY_SECONDS)
        if claim is None:
            raise PublishError(
                f"Taskcluster did not return the task claim for {task_id}"
            )
        run = TaskRun(
            task_id=task_id,
            run_id=str(claim["runId"]),
            task=task,
            queue=self.queue,
            initial_credentials=claim["credentials"],
        )
        lease = ClaimLease(self.root_url, run, self.taskcluster)
        lease.start()
        return run, lease

    def _upload_artifact(
        self, lease: ClaimLease, name: str, path: Path, expires: str
    ) -> None:
        size = path.stat().st_size
        artifact_request = {
            "storageType": "object",
            "expires": expires,
            "contentType": "application/octet-stream",
            "contentLength": size,
        }
        response = lease.queue().createArtifact(
            lease.run.task_id,
            lease.run.run_id,
            name,
            artifact_request,
        )
        if response.get("storageType") != "object":
            raise PublishError("Queue did not return an object artifact upload")
        required = ("projectId", "name", "uploadId", "expires", "credentials")
        if any(key not in response for key in required):
            raise PublishError("Queue returned an incomplete object upload response")
        object_service = self.taskcluster.Object(
            _client_options(self.root_url, response["credentials"])
        )
        with path.open("rb") as file_obj:
            self.upload_from_file(
                file=file_obj,
                projectId=response["projectId"],
                name=response["name"],
                contentType="application/octet-stream",
                contentLength=size,
                expires=response["expires"],
                uploadId=response["uploadId"],
                objectService=object_service,
            )
        lease.queue().finishArtifact(
            lease.run.task_id,
            lease.run.run_id,
            name,
            {"uploadId": response["uploadId"]},
        )

    def _publish_task_artifact(
        self, label: str, path: Path, artifact_name: str
    ) -> TaskRun:
        run, lease = self._create_and_claim(label)
        try:
            artifact_expires = _date(self.now(UTC) + timedelta(days=ARTIFACT_TTL_DAYS))
            self._upload_artifact(lease, artifact_name, path, artifact_expires)
            lease.queue().reportCompleted(run.task_id, run.run_id)
        except Exception:
            try:
                lease.queue().reportFailed(run.task_id, run.run_id)
            except Exception:
                LOG.exception("Could not report publisher task failure")
            raise
        finally:
            lease.stop()
        return run

    def _insert(self, namespace: str, run: TaskRun) -> None:
        task = self.queue.task(run.task_id)
        self.index.insertTask(
            namespace,
            {
                "data": {},
                "expires": task["expires"],
                "rank": self.rank,
                "taskId": run.task_id,
            },
        )

    def _docker_publish(
        self, name: str, sha: str, archs: list[str], archives: dict[str, Path]
    ) -> Path:
        username = self._required("DOCKERHUB_USERNAME")
        token = self._required("DOCKERHUB_TOKEN")
        repository = f"docker.io/{IMAGE_NAMESPACE}/{name}"
        with tempfile.TemporaryDirectory(prefix="orion-publish-") as temp_dir:
            temp_path = Path(temp_dir)
            refs: dict[str, str] = {}
            self.command(
                "podman",
                "login",
                "--username",
                username,
                "--password-stdin",
                "docker.io",
                input_text=token,
            )
            for arch in archs:
                self.command("podman", "load", "--input", str(archives[arch]))
                latest_arch = f"{repository}:latest-{arch}"
                sha_arch = f"{repository}:{sha}-{arch}"
                self.command("podman", "tag", latest_arch, sha_arch)
                refs[arch] = latest_arch
                self.command(
                    "podman",
                    "push",
                    "--digestfile",
                    str(temp_path / f"{arch}.digest"),
                    sha_arch,
                )
                self.command("podman", "push", latest_arch)

            archive = temp_path / f"{name}.tar"
            self.command(
                "podman",
                "save",
                "--multi-image-archive",
                "--output",
                str(archive),
                *[refs[arch] for arch in archs],
            )
            combined = temp_path / f"{name}.tar.zst"
            self.command(
                "zstd",
                "--quiet",
                "--threads=0",
                "--force",
                str(archive),
                "--output",
                str(combined),
            )
            manifest = f"{repository}:latest"
            self.command("podman", "manifest", "create", "--amend", manifest)
            for arch in archs:
                self.command(
                    "podman",
                    "manifest",
                    "add",
                    manifest,
                    f"containers-storage:{refs[arch]}",
                )
            self.command(
                "podman", "manifest", "push", "--all", manifest, f"docker://{manifest}"
            )

            sha_manifest = f"{repository}:{sha}"
            self.command("podman", "manifest", "create", "--amend", sha_manifest)
            for arch in archs:
                self.command(
                    "podman",
                    "manifest",
                    "add",
                    sha_manifest,
                    f"containers-storage:{repository}:{sha}-{arch}",
                )
            self.command(
                "podman",
                "manifest",
                "push",
                "--all",
                sha_manifest,
                f"docker://{sha_manifest}",
            )
            # Keep a local copy outside TemporaryDirectory for the TC upload caller.
            fd, result_name = tempfile.mkstemp(prefix=f"{name}-", suffix=".tar.zst")
            os.close(fd)
            result = Path(result_name)
            shutil.copyfile(combined, result)
            return result

    def publish_service(
        self, name: str, service: dict[str, Any], artifact_dir: Path, sha: str
    ) -> None:
        kind = service.get("kind")
        if kind == "msys":
            path = artifact_dir / name / "msys2.tar.bz2"
            if not path.is_file():
                raise PublishError(f"missing MSYS artifact: {path}")
            run = self._publish_task_artifact(name, path, "public/msys2.tar.bz2")
            self._insert(f"project.fuzzing.orion.{name}.rev.{sha}", run)
            self._insert(f"project.fuzzing.orion.{name}.main", run)
            return
        if kind != "docker":
            raise PublishError(f"service {name} has unsupported kind {kind!r}")
        archs = service.get("archs")
        if (
            not isinstance(archs, list)
            or not archs
            or any(a not in {"amd64", "arm64"} for a in archs)
        ):
            raise PublishError(f"service {name} must list amd64 and/or arm64 in archs")
        archives = {
            arch: artifact_dir / name / f"{name}-{arch}.tar.zst" for arch in archs
        }
        for path in archives.values():
            if not path.is_file():
                raise PublishError(f"missing Docker image archive: {path}")

        per_arch_runs = {}
        for arch in archs:
            per_arch_runs[arch] = self._publish_task_artifact(
                f"{name}-{arch}", archives[arch], f"public/{name}.tar.zst"
            )
        combined_path = self._docker_publish(name, sha, archs, archives)
        try:
            combined_run = self._publish_task_artifact(
                f"{name}-combined", combined_path, f"public/{name}.tar.zst"
            )
        finally:
            combined_path.unlink(missing_ok=True)

        for arch, run in per_arch_runs.items():
            self._insert(f"project.fuzzing.orion.{name}.{arch}.rev.{sha}", run)
            self._insert(f"project.fuzzing.orion.{name}.{arch}.main", run)
        self._insert(f"project.fuzzing.orion.{name}.rev.{sha}", combined_run)
        self._insert(f"project.fuzzing.orion.{name}.main", combined_run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--service", required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    require_trusted_main()
    plan = load_plan(args.plan)
    try:
        service = plan["services"][args.service]
    except KeyError as exc:
        raise PublishError(f"service {args.service!r} is absent from plan") from exc
    import taskcluster
    from taskcluster.upload import uploadFromFile

    Publisher(
        taskcluster=taskcluster,
        upload_from_file=uploadFromFile,
        env=dict(os.environ),
    ).publish_service(args.service, service, args.artifacts, plan["head"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
