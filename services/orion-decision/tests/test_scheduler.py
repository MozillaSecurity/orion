# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Tests for Orion scheduler"""

from datetime import datetime
from pathlib import Path

from taskcluster.utils import stringDate

from orion_decision import ARTIFACTS_EXPIRE
from orion_decision import DEADLINE
from orion_decision import MAX_RUN_TIME
from orion_decision import OWNER_EMAIL
from orion_decision import PROVISIONER_ID
from orion_decision import SCHEDULER_ID
from orion_decision import SOURCE_URL
from orion_decision import WORKER_TYPE
from orion_decision.git import GithubEvent
from orion_decision.scheduler import Scheduler


FIXTURES = (Path(__file__).parent / "fixtures").resolve()


def test_main(mocker):
    """test scheduler main"""
    evt = mocker.patch("orion_decision.scheduler.GithubEvent", autospec=True)
    svcs = mocker.patch("orion_decision.scheduler.Services", autospec=True)
    mark = mocker.patch.object(Scheduler, "mark_services_for_rebuild", autospec=True)
    create = mocker.patch.object(Scheduler, "create_tasks", autospec=True)
    args = mocker.Mock()
    assert Scheduler.main(args) == 0
    assert svcs.call_count == 1
    assert evt.from_taskcluster.call_count == 1
    assert evt.from_taskcluster.return_value.cleanup.call_count == 1
    assert mark.call_count == 1
    assert create.call_count == 1


def test_mark_rebuild_01(mocker):
    """test that "/force-rebuild" marks all services dirty"""
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.commit_message = "/force-rebuild"
    sched = Scheduler(evt, None, "group", "secret", "branch")
    sched.mark_services_for_rebuild()
    for svc in sched.services.values():
        assert svc.dirty
    assert evt.list_changed_paths.call_count == 0


def test_mark_rebuild_02(mocker):
    """test that changed paths mark dependent services dirty"""
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.commit_message = ""
    evt.list_changed_paths.return_value = [root / "recipes" / "linux" / "install.sh"]
    sched = Scheduler(evt, None, "group", "secret", "branch")
    sched.mark_services_for_rebuild()
    assert evt.list_changed_paths.call_count == 1
    assert sched.services["test1"].dirty
    assert sched.services["test2"].dirty
    assert not sched.services["test3"].dirty


def test_create_01(mocker):
    """test no task creation"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.utcnow()
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    sched = Scheduler(evt, now, "group", "secret", "push")
    sched.create_tasks()
    assert queue.createTask.call_count == 0


def test_create_02(mocker):
    """test non-push task creation"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.utcnow()
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.commit = "commit"
    evt.branch = "main"
    evt.clone_url = "https://example.com"
    evt.pull_request = None
    sched = Scheduler(evt, now, "group", "secret", "push")
    sched.services["test1"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 1
    _, task = queue.createTask.call_args.args
    assert task == {
        "taskGroupId": "group",
        "dependencies": [],
        "created": stringDate(now),
        "deadline": stringDate(now + DEADLINE),
        "provisionerId": PROVISIONER_ID,
        "schedulerId": SCHEDULER_ID,
        "workerType": WORKER_TYPE,
        "payload": {
            "artifacts": {
                "public/test1.tar": {
                    "expires": stringDate(now + ARTIFACTS_EXPIRE),
                    "path": "/image.tar",
                    "type": "file",
                },
            },
            "command": ["build.sh"],
            "env": {
                "ARCHIVE_PATH": "/image.tar",
                "DOCKERFILE": "test1/Dockerfile",
                "GIT_REPOSITORY": "https://example.com",
                "GIT_REVISION": "commit",
                "IMAGE_NAME": "test1",
                "LOAD_DEPS": "0",
            },
            "features": {"privileged": True},
            "image": "mozillasecurity/taskboot:latest",
            "maxRunTime": MAX_RUN_TIME.total_seconds(),
        },
        "routes": [
            "index.project.fuzzing.orion.test1.rev.commit",
            "index.project.fuzzing.orion.test1.main",
        ],
        "scopes": [
            "docker-worker:capability:privileged",
            "queue:route:index.project.fuzzing.orion.*",
            f"queue:scheduler-id:{SCHEDULER_ID}",
        ],
        "metadata": {
            "description": "Build the docker image for test1 tasks",
            "name": "Orion test1 docker build",
            "owner": OWNER_EMAIL,
            "source": SOURCE_URL,
        },
    }


def test_create_03(mocker):
    """test push task creation"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.utcnow()
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.commit = "commit"
    evt.branch = "push"
    evt.event_type = "push"
    evt.clone_url = "https://example.com"
    evt.pull_request = None
    sched = Scheduler(evt, now, "group", "secret", "push")
    sched.services["test1"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 2
    build_task_id, build_task = queue.createTask.call_args_list[0].args
    assert build_task == {
        "taskGroupId": "group",
        "dependencies": [],
        "created": stringDate(now),
        "deadline": stringDate(now + DEADLINE),
        "provisionerId": PROVISIONER_ID,
        "schedulerId": SCHEDULER_ID,
        "workerType": WORKER_TYPE,
        "payload": {
            "artifacts": {
                "public/test1.tar": {
                    "expires": stringDate(now + ARTIFACTS_EXPIRE),
                    "path": "/image.tar",
                    "type": "file",
                },
            },
            "command": ["build.sh"],
            "env": {
                "ARCHIVE_PATH": "/image.tar",
                "DOCKERFILE": "test1/Dockerfile",
                "GIT_REPOSITORY": "https://example.com",
                "GIT_REVISION": "commit",
                "IMAGE_NAME": "test1",
                "LOAD_DEPS": "0",
            },
            "features": {"privileged": True},
            "image": "mozillasecurity/taskboot:latest",
            "maxRunTime": MAX_RUN_TIME.total_seconds(),
        },
        "routes": [
            "index.project.fuzzing.orion.test1.rev.commit",
            "index.project.fuzzing.orion.test1.push",
        ],
        "scopes": [
            "docker-worker:capability:privileged",
            "queue:route:index.project.fuzzing.orion.*",
            f"queue:scheduler-id:{SCHEDULER_ID}",
        ],
        "metadata": {
            "description": "Build the docker image for test1 tasks",
            "name": "Orion test1 docker build",
            "owner": OWNER_EMAIL,
            "source": SOURCE_URL,
        },
    }
    _, push_task = queue.createTask.call_args_list[1].args
    assert push_task == {
        "taskGroupId": "group",
        "dependencies": [build_task_id],
        "created": stringDate(now),
        "deadline": stringDate(now + DEADLINE),
        "provisionerId": PROVISIONER_ID,
        "schedulerId": SCHEDULER_ID,
        "workerType": WORKER_TYPE,
        "payload": {
            "command": ["taskboot", "push-artifact"],
            "features": {"taskclusterProxy": True},
            "image": "mozillasecurity/taskboot:latest",
            "maxRunTime": MAX_RUN_TIME.total_seconds(),
            "env": {"TASKCLUSTER_SECRET": "secret"},
        },
        "scopes": [
            f"queue:scheduler-id:{SCHEDULER_ID}",
            "secrets:get:secret",
        ],
        "metadata": {
            "description": "Publish the docker image for test1 tasks",
            "name": "Orion test1 docker push",
            "owner": OWNER_EMAIL,
            "source": SOURCE_URL,
        },
    }


def test_create_04(mocker):
    """test dependent tasks creation"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.utcnow()
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.commit = "commit"
    evt.branch = "main"
    evt.clone_url = "https://example.com"
    evt.pull_request = None
    sched = Scheduler(evt, now, "group", "secret", "push")
    sched.services["test1"].dirty = True
    sched.services["test2"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 2
    task1_id, task1 = queue.createTask.call_args_list[0].args
    assert task1 == {
        "taskGroupId": "group",
        "dependencies": [],
        "created": stringDate(now),
        "deadline": stringDate(now + DEADLINE),
        "provisionerId": PROVISIONER_ID,
        "schedulerId": SCHEDULER_ID,
        "workerType": WORKER_TYPE,
        "payload": {
            "artifacts": {
                "public/test1.tar": {
                    "expires": stringDate(now + ARTIFACTS_EXPIRE),
                    "path": "/image.tar",
                    "type": "file",
                },
            },
            "command": ["build.sh"],
            "env": {
                "ARCHIVE_PATH": "/image.tar",
                "DOCKERFILE": "test1/Dockerfile",
                "GIT_REPOSITORY": "https://example.com",
                "GIT_REVISION": "commit",
                "IMAGE_NAME": "test1",
                "LOAD_DEPS": "0",
            },
            "features": {"privileged": True},
            "image": "mozillasecurity/taskboot:latest",
            "maxRunTime": MAX_RUN_TIME.total_seconds(),
        },
        "routes": [
            "index.project.fuzzing.orion.test1.rev.commit",
            "index.project.fuzzing.orion.test1.main",
        ],
        "scopes": [
            "docker-worker:capability:privileged",
            "queue:route:index.project.fuzzing.orion.*",
            f"queue:scheduler-id:{SCHEDULER_ID}",
        ],
        "metadata": {
            "description": "Build the docker image for test1 tasks",
            "name": "Orion test1 docker build",
            "owner": OWNER_EMAIL,
            "source": SOURCE_URL,
        },
    }
    _, task2 = queue.createTask.call_args_list[1].args
    assert task2 == {
        "taskGroupId": "group",
        "dependencies": [task1_id],
        "created": stringDate(now),
        "deadline": stringDate(now + DEADLINE),
        "provisionerId": PROVISIONER_ID,
        "schedulerId": SCHEDULER_ID,
        "workerType": WORKER_TYPE,
        "payload": {
            "artifacts": {
                "public/test2.tar": {
                    "expires": stringDate(now + ARTIFACTS_EXPIRE),
                    "path": "/image.tar",
                    "type": "file",
                },
            },
            "command": ["build.sh"],
            "env": {
                "ARCHIVE_PATH": "/image.tar",
                "DOCKERFILE": "test2/Dockerfile",
                "GIT_REPOSITORY": "https://example.com",
                "GIT_REVISION": "commit",
                "IMAGE_NAME": "test2",
                "LOAD_DEPS": "1",
            },
            "features": {"privileged": True},
            "image": "mozillasecurity/taskboot:latest",
            "maxRunTime": MAX_RUN_TIME.total_seconds(),
        },
        "routes": [
            "index.project.fuzzing.orion.test2.rev.commit",
            "index.project.fuzzing.orion.test2.main",
        ],
        "scopes": [
            "docker-worker:capability:privileged",
            "queue:route:index.project.fuzzing.orion.*",
            f"queue:scheduler-id:{SCHEDULER_ID}",
        ],
        "metadata": {
            "description": "Build the docker image for test2 tasks",
            "name": "Orion test2 docker build",
            "owner": OWNER_EMAIL,
            "source": SOURCE_URL,
        },
    }


def test_create_05(mocker):
    """test no tasks are created for release event"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.utcnow()
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.event_type = "release"
    sched = Scheduler(evt, now, "group", "secret", "push")
    sched.services["test1"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 0


def test_create_06(mocker):
    """test no tasks are created for --dry-run"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.utcnow()
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.event_type = "push"
    evt.commit = "commit"
    evt.branch = "push"
    evt.pull_request = None
    evt.clone_url = "https://example.com"
    sched = Scheduler(evt, now, "group", "secret", "push", dry_run=True)
    sched.services["test1"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 0


def test_create_07(mocker):
    """test PR doesn't create push task"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.utcnow()
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.commit = "commit"
    evt.branch = "push"
    evt.clone_url = "https://example.com"
    evt.pull_request = 1
    sched = Scheduler(evt, now, "group", "secret", "push")
    sched.services["test1"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 1
    _, task = queue.createTask.call_args.args
    assert task == {
        "taskGroupId": "group",
        "dependencies": [],
        "created": stringDate(now),
        "deadline": stringDate(now + DEADLINE),
        "provisionerId": PROVISIONER_ID,
        "schedulerId": SCHEDULER_ID,
        "workerType": WORKER_TYPE,
        "payload": {
            "artifacts": {
                "public/test1.tar": {
                    "expires": stringDate(now + ARTIFACTS_EXPIRE),
                    "path": "/image.tar",
                    "type": "file",
                },
            },
            "command": ["build.sh"],
            "env": {
                "ARCHIVE_PATH": "/image.tar",
                "DOCKERFILE": "test1/Dockerfile",
                "GIT_REPOSITORY": "https://example.com",
                "GIT_REVISION": "commit",
                "IMAGE_NAME": "test1",
                "LOAD_DEPS": "0",
            },
            "features": {"privileged": True},
            "image": "mozillasecurity/taskboot:latest",
            "maxRunTime": MAX_RUN_TIME.total_seconds(),
        },
        "routes": [
            "index.project.fuzzing.orion.test1.rev.commit",
            "index.project.fuzzing.orion.test1.pull_request.1",
        ],
        "scopes": [
            "docker-worker:capability:privileged",
            "queue:route:index.project.fuzzing.orion.*",
            f"queue:scheduler-id:{SCHEDULER_ID}",
        ],
        "metadata": {
            "description": "Build the docker image for test1 tasks",
            "name": "Orion test1 docker build",
            "owner": OWNER_EMAIL,
            "source": SOURCE_URL,
        },
    }
