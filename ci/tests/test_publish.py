from __future__ import annotations

from datetime import datetime, timezone
from inspect import signature
from pathlib import Path
from unittest.mock import create_autospec

import pytest
import taskcluster
from taskcluster.aio.upload import upload as sdk_upload

from ci.publish import Publisher, PublishError, require_trusted_main

UTC = timezone.utc


class FakeQueue:
    def __init__(self, events: list[tuple], holder: dict) -> None:
        self.events = events
        self.holder = holder

    def createTask(self, task_id, task):
        self.events.append(("create", task_id, task))
        self.holder["task_id"] = task_id
        self.holder["task"] = task

    def claimWork(self, task_queue, payload):
        self.events.append(("claim-work", task_queue, payload))
        if self.holder.pop("empty_claim_once", False):
            return {"tasks": []}
        return {
            "tasks": [
                {
                    "runId": 0,
                    "status": {"taskId": self.holder["task_id"]},
                    "credentials": {
                        "clientId": "temporary",
                        "accessToken": "temp",
                        "certificate": "signed certificate",
                    },
                }
            ]
        }

    def createArtifact(self, task_id, run_id, name, payload):
        self.events.append(("create-artifact", name, payload))
        return {
            "storageType": "object",
            "projectId": "proj-fuzzing",
            "name": name,
            "uploadId": "upload-id",
            "expires": payload["expires"],
            "credentials": {"clientId": "object-uploader", "accessToken": "obj"},
        }

    def finishArtifact(self, task_id, run_id, name, payload):
        self.events.append(("finish-artifact", name, payload))

    def reportCompleted(self, task_id, run_id):
        self.events.append(("completed", task_id))

    def reportFailed(self, task_id, run_id):
        self.events.append(("failed", task_id))

    def task(self, task_id):
        return {"expires": self.holder["task"]["expires"]}

    def reclaimTask(self, task_id, run_id):
        return {
            "credentials": {
                "clientId": "temporary2",
                "accessToken": "temp2",
                "certificate": "renewed certificate",
            }
        }


class FakeIndex:
    def __init__(self, events: list[tuple]) -> None:
        self.events = events

    def insertTask(self, namespace, payload):
        self.events.append(("index", namespace, payload))


class FakeTaskcluster:
    def __init__(self) -> None:
        self.events: list[tuple] = []
        self.holder: dict = {}
        self.options: list[dict] = []
        self.task_counter = 0
        self.queues = []
        self.indexes = []
        self.objects = []

    def Queue(self, options):
        self.options.append(options)
        queue = create_autospec(taskcluster.Queue, instance=True, spec_set=True)
        shim = FakeQueue(self.events, self.holder)
        for method in (
            "createTask",
            "claimWork",
            "createArtifact",
            "finishArtifact",
            "reportCompleted",
            "reportFailed",
            "task",
            "reclaimTask",
        ):
            getattr(queue, method).side_effect = getattr(shim, method)
        self.queues.append(queue)
        return queue

    def Index(self, _options):
        index = create_autospec(taskcluster.Index, instance=True, spec_set=True)
        index.insertTask.side_effect = FakeIndex(self.events).insertTask
        self.indexes.append(index)
        return index

    def Object(self, options):
        self.events.append(("object-client", options))
        obj = create_autospec(taskcluster.Object, instance=True, spec_set=True)
        self.objects.append(obj)
        return obj

    def slugId(self):
        self.task_counter += 1
        return f"task-id-{self.task_counter}"


def _publisher(tc: FakeTaskcluster) -> Publisher:
    def upload_from_file(**kwargs):
        file_obj = kwargs["file"]
        content = file_obj.read()
        # Match taskcluster.upload.uploadFromFile: it forwards every other
        # argument to the async upload helper and supplies readerFactory.
        sdk_kwargs = {key: value for key, value in kwargs.items() if key != "file"}
        signature(sdk_upload).bind(**sdk_kwargs, readerFactory=lambda: None)
        tc.events.append(("object-upload", content, kwargs))

    return Publisher(
        taskcluster=tc,
        upload_from_file=upload_from_file,
        env={
            "TASKCLUSTER_CLIENT_ID": "client",
            "TASKCLUSTER_ACCESS_TOKEN": "token",
            "GITHUB_RUN_ID": "12345",
            "GITHUB_RUN_NUMBER": "8",
            "GITHUB_RUN_ATTEMPT": "1",
        },
        now=lambda _tz: datetime(2026, 1, 1, tzinfo=UTC),
        sleep=lambda _seconds: None,
    )


def test_main_guard_requires_trusted_main_event() -> None:
    require_trusted_main({"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/main"})
    require_trusted_main(
        {"GITHUB_EVENT_NAME": "schedule", "GITHUB_REF": "refs/heads/main"}
    )
    require_trusted_main(
        {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main"}
    )
    with pytest.raises(PublishError, match="only for main branch events"):
        require_trusted_main(
            {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_REF": "refs/heads/main"}
        )


def test_msys_upload_finishes_before_legacy_indices(tmp_path: Path) -> None:
    artifact = tmp_path / "service" / "msys2.tar.bz2"
    artifact.parent.mkdir()
    artifact.write_bytes(b"msys bundle")
    tc = FakeTaskcluster()
    tc.holder["empty_claim_once"] = True
    _publisher(tc).publish_service("service", {"kind": "msys"}, tmp_path, "a" * 40)

    event_names = [event[0] for event in tc.events]
    assert event_names.index("completed") < event_names.index("index")
    assert [event[1] for event in tc.events if event[0] == "index"] == [
        "project.fuzzing.orion.service.rev." + "a" * 40,
        "project.fuzzing.orion.service.main",
    ]
    uploaded = next(event for event in tc.events if event[0] == "create-artifact")
    assert uploaded[1] == "public/msys2.tar.bz2"
    assert uploaded[2]["storageType"] == "object"
    temporary_options = [
        options
        for options in tc.options
        if options["credentials"]["clientId"] == "temporary"
    ]
    assert temporary_options
    assert all(
        options["credentials"]["certificate"] == "signed certificate"
        for options in temporary_options
    )
    assert sum(event[0] == "claim-work" for event in tc.events) == 2


def test_object_upload_failure_never_inserts_index(tmp_path: Path) -> None:
    artifact = tmp_path / "service" / "msys2.tar.bz2"
    artifact.parent.mkdir()
    artifact.write_bytes(b"msys bundle")
    tc = FakeTaskcluster()

    def fail_upload(**kwargs):
        raise RuntimeError("object upload failure")

    publisher = Publisher(
        taskcluster=tc,
        upload_from_file=fail_upload,
        env={
            "TASKCLUSTER_CLIENT_ID": "client",
            "TASKCLUSTER_ACCESS_TOKEN": "token",
            "GITHUB_RUN_ID": "12345",
            "GITHUB_RUN_NUMBER": "8",
            "GITHUB_RUN_ATTEMPT": "1",
        },
        now=lambda _tz: datetime(2026, 1, 1, tzinfo=UTC),
        sleep=lambda _seconds: None,
    )
    with pytest.raises(RuntimeError, match="object upload failure"):
        publisher.publish_service("service", {"kind": "msys"}, tmp_path, "b" * 40)

    assert not any(event[0] == "index" for event in tc.events)
    assert any(event[0] == "failed" for event in tc.events)


def test_object_upload_uses_sdk_parameters_and_finish_schema(tmp_path: Path) -> None:
    path = tmp_path / "archive.tar.zst"
    content = b"archive bytes"
    path.write_bytes(content)
    tc = FakeTaskcluster()
    publisher = _publisher(tc)
    _run, lease = publisher._create_and_claim("object")
    try:
        publisher._upload_artifact(
            lease, "public/archive.tar.zst", path, "2030-01-01T00:00:00Z"
        )
    finally:
        lease.stop()

    create = next(event for event in tc.events if event[0] == "create-artifact")
    assert create[2] == {
        "storageType": "object",
        "expires": "2030-01-01T00:00:00Z",
        "contentType": "application/octet-stream",
        "contentLength": len(content),
    }
    upload = next(event for event in tc.events if event[0] == "object-upload")
    assert upload[1] == content
    assert upload[2]["projectId"] == "proj-fuzzing"
    assert upload[2]["name"] == "public/archive.tar.zst"
    assert upload[2]["contentType"] == "application/octet-stream"
    assert upload[2]["contentLength"] == len(content)
    assert upload[2]["expires"] == "2030-01-01T00:00:00Z"
    assert upload[2]["uploadId"] == "upload-id"
    assert upload[2]["objectService"] is tc.objects[0]
    object_options = next(event for event in tc.events if event[0] == "object-client")
    assert object_options[1] == {
        "rootUrl": "https://firefox-ci-tc.services.mozilla.com",
        "credentials": {"clientId": "object-uploader", "accessToken": "obj"},
        "maxRetries": 5,
    }
    finish = next(event for event in tc.events if event[0] == "finish-artifact")
    assert finish[2] == {"uploadId": "upload-id"}


def test_docker_publication_uploads_multiarch_and_indexes_after_registry(
    tmp_path: Path,
) -> None:
    service_dir = tmp_path / "image"
    service_dir.mkdir()
    for arch in ("amd64", "arm64"):
        (service_dir / f"image-{arch}.tar.zst").write_bytes(f"image {arch}".encode())
    tc = FakeTaskcluster()

    def command(*args: str, input_text: str | None = None) -> str:
        del input_text
        tc.events.append(("command", *args))
        if args[0] == "podman" and args[1] == "save":
            Path(args[args.index("--output") + 1]).write_bytes(b"multi image archive")
        elif args[0] == "zstd":
            Path(args[args.index("--output") + 1]).write_bytes(b"compressed archive")
        return ""

    env = {
        "TASKCLUSTER_CLIENT_ID": "client",
        "TASKCLUSTER_ACCESS_TOKEN": "token",
        "DOCKERHUB_USERNAME": "user",
        "DOCKERHUB_TOKEN": "secret",
        "GITHUB_RUN_ID": "98765",
        "GITHUB_RUN_NUMBER": "9",
        "GITHUB_RUN_ATTEMPT": "1",
    }
    publisher = Publisher(
        taskcluster=tc,
        upload_from_file=_publisher(tc).upload_from_file,
        env=env,
        command=command,
        now=lambda _tz: datetime(2026, 1, 1, tzinfo=UTC),
    )

    publisher.publish_service(
        "image", {"kind": "docker", "archs": ["amd64", "arm64"]}, tmp_path, "c" * 40
    )

    events = tc.events
    docker_pushes = [
        index
        for index, event in enumerate(events)
        if event[0] == "command"
        and event[1:3] == ("podman", "manifest")
        and "push" in event
    ]
    index_writes = [index for index, event in enumerate(events) if event[0] == "index"]
    assert len(docker_pushes) == 2
    assert len(index_writes) == 6
    assert min(index_writes) > max(docker_pushes)
    assert sum(event[0] == "completed" for event in events) == 3
    assert {event[1] for event in events if event[0] == "index"} == {
        "project.fuzzing.orion.image.amd64.rev." + "c" * 40,
        "project.fuzzing.orion.image.arm64.rev." + "c" * 40,
        "project.fuzzing.orion.image.rev." + "c" * 40,
        "project.fuzzing.orion.image.amd64.main",
        "project.fuzzing.orion.image.arm64.main",
        "project.fuzzing.orion.image.main",
    }
