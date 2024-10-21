# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Tests for Orion cron scheduler"""

from datetime import datetime, timedelta, timezone
from logging import getLogger
from pathlib import Path
from typing import Set

import pytest
from freezegun import freeze_time
from pytest_mock import MockerFixture
from taskcluster.exceptions import TaskclusterRestFailure
from taskcluster.utils import stringDate
from yaml import safe_load as yaml_load

from orion_decision import (
    ARTIFACTS_EXPIRE,
    CRON_PERIOD,
    DEADLINE,
    MAX_RUN_TIME,
    OWNER_EMAIL,
    PROVISIONER_ID,
    SOURCE_URL,
    WORKER_TYPE,
)
from orion_decision.cron import CronScheduler
from orion_decision.git import GitRepo
from orion_decision.scheduler import BUILD_TASK, PUSH_TASK

FIXTURES = (Path(__file__).parent / "fixtures").resolve()
LOG = getLogger(__name__)


def test_cron_main(mocker: MockerFixture) -> None:
    """test cron scheduler main"""
    repo = mocker.patch("orion_decision.cron.GitRepo", autospec=True)
    svcs = mocker.patch("orion_decision.cron.Services", autospec=True)
    mark = mocker.patch.object(
        CronScheduler, "mark_services_for_rebuild", autospec=True
    )
    create = mocker.patch.object(CronScheduler, "create_tasks", autospec=True)
    args = mocker.Mock()
    assert CronScheduler.main(args) == 0
    assert svcs.call_count == 1
    assert repo.call_count == 1
    assert repo.return_value.cleanup.call_count == 1
    assert mark.call_count == 1
    assert create.call_count == 1


@freeze_time()
@pytest.mark.parametrize(
    "expired_svcs,missing_svcs,dirty_svcs",
    [
        ({"test1"}, {}, {"test1", "test2"}),
        ({"test2"}, {}, {"test2"}),
        ({}, {"test1"}, {"test1", "test2"}),
        ({"test5"}, {}, {"test5", "test6", "test7"}),
    ],
)
def test_cron_mark_rebuild(
    mocker: MockerFixture,
    expired_svcs: Set[str],
    missing_svcs: Set[str],
    dirty_svcs: Set[str],
) -> None:
    """test mark_services_for_rebuild"""
    now = datetime.now(timezone.utc)
    taskcluster = mocker.patch("orion_decision.cron.Taskcluster", autospec=True)
    index = mocker.Mock()
    queue = mocker.Mock()

    def _get_service(name):
        return {
            "index": index,
            "queue": queue,
        }[name]

    taskcluster.get_service.side_effect = _get_service
    queue = taskcluster.get_service.return_value

    def _find_task(path):
        for svc in expired_svcs:
            if f".{svc}." in path:
                LOG.debug("%s is expired", path)
                return {"taskId": "expired"}
        for svc in missing_svcs:
            if f".{svc}." in path:
                LOG.debug("%s is 404", path)
                raise TaskclusterRestFailure("404", None)
        LOG.debug("%s is not expired", path)
        return {"taskId": "unexpired"}

    def _get_task(task_id):
        return {
            "expired": {
                "deadline": (now - timedelta(days=7)).isoformat(),
                "expires": now.isoformat(),
            },
            "unexpired": {
                "deadline": now.isoformat(),
                "expires": (now + CRON_PERIOD * 2).isoformat(),
            },
        }[task_id]

    index.findTask.side_effect = _find_task
    queue.task.side_effect = _get_task
    root = FIXTURES / "services03"
    repo = mocker.Mock(spec=GitRepo.from_existing(root))
    repo.path = root
    repo.git = mocker.Mock(return_value="\n".join(str(p) for p in root.glob("**/*")))
    sched = CronScheduler(
        repo,
        "group",
        "scheduler",
        "secret",
        "/path/to/repo",
        "push",
    )
    sched.mark_services_for_rebuild()
    for svc in sched.services.values():
        assert svc.dirty == bool(svc.name in dirty_svcs)


def test_cron_create_01(mocker: MockerFixture) -> None:
    """test no task creation"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    root = FIXTURES / "services03"
    repo = mocker.Mock(spec=GitRepo.from_existing(root))
    repo.path = root
    repo.git = mocker.Mock(return_value="\n".join(str(p) for p in root.glob("**/*")))
    sched = CronScheduler(
        repo,
        "group",
        "scheduler",
        "secret",
        "/path/to/repo",
        "push",
    )
    sched.create_tasks()
    assert queue.createTask.call_count == 0


@freeze_time()
def test_cron_create_02(mocker: MockerFixture) -> None:
    """test push task creation"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.now(timezone.utc)
    root = FIXTURES / "services03"
    repo = mocker.Mock(spec=GitRepo.from_existing(root))
    repo.path = root
    repo.git = mocker.Mock(return_value="\n".join(str(p) for p in root.glob("**/*")))
    repo.head.return_value = "commit"
    sched = CronScheduler(
        repo,
        "group",
        "scheduler",
        "secret",
        "https://example.com",
        "push",
    )
    sched.services["test1"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 2
    build_task_id, build_task = queue.createTask.call_args_list[0][0]
    assert build_task == yaml_load(
        BUILD_TASK.substitute(
            clone_url="https://example.com",
            commit="commit",
            deadline=stringDate(now + DEADLINE),
            dockerfile="test1/Dockerfile",
            expires=stringDate(now + ARTIFACTS_EXPIRE),
            load_deps="0",
            max_run_time=int(MAX_RUN_TIME.total_seconds()),
            now=stringDate(now),
            owner_email=OWNER_EMAIL,
            provisioner=PROVISIONER_ID,
            scheduler="scheduler",
            service_name="test1",
            source_url=SOURCE_URL,
            task_group="group",
            worker=WORKER_TYPE,
            arch="amd64",
        )
    )
    _, push_task = queue.createTask.call_args_list[1][0]
    push_expected = yaml_load(
        PUSH_TASK.substitute(
            clone_url="https://example.com",
            commit="commit",
            deadline=stringDate(now + DEADLINE),
            docker_secret="secret",
            max_run_time=int(MAX_RUN_TIME.total_seconds()),
            now=stringDate(now),
            owner_email=OWNER_EMAIL,
            provisioner=PROVISIONER_ID,
            scheduler="scheduler",
            service_name="test1",
            skip_docker="0",
            source_url=SOURCE_URL,
            task_group="group",
            task_index="project.fuzzing.orion.test1.push",
            worker=WORKER_TYPE,
            archs=str(["amd64"]),
        )
    )
    push_expected["dependencies"].append(build_task_id)
    assert push_task == push_expected


@freeze_time()
def test_cron_create_03(mocker: MockerFixture) -> None:
    """test dependent tasks creation"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.now(timezone.utc)
    root = FIXTURES / "services03"
    repo = mocker.Mock(spec=GitRepo.from_existing(root))
    repo.path = root
    repo.git = mocker.Mock(return_value="\n".join(str(p) for p in root.glob("**/*")))
    repo.head.return_value = "commit"
    sched = CronScheduler(
        repo,
        "group",
        "scheduler",
        "secret",
        "https://example.com",
        "push",
    )
    sched.services["test1"].dirty = True
    sched.services["test2"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 4
    task1_id, task1 = queue.createTask.call_args_list[0][0]
    assert task1 == yaml_load(
        BUILD_TASK.substitute(
            clone_url="https://example.com",
            commit="commit",
            deadline=stringDate(now + DEADLINE),
            dockerfile="test1/Dockerfile",
            expires=stringDate(now + ARTIFACTS_EXPIRE),
            load_deps="0",
            max_run_time=int(MAX_RUN_TIME.total_seconds()),
            now=stringDate(now),
            owner_email=OWNER_EMAIL,
            provisioner=PROVISIONER_ID,
            scheduler="scheduler",
            service_name="test1",
            source_url=SOURCE_URL,
            task_group="group",
            worker=WORKER_TYPE,
            arch="amd64",
        )
    )
    _, task2 = queue.createTask.call_args_list[1][0]
    expected2 = yaml_load(
        PUSH_TASK.substitute(
            clone_url="https://example.com",
            commit="commit",
            deadline=stringDate(now + DEADLINE),
            docker_secret="secret",
            max_run_time=int(MAX_RUN_TIME.total_seconds()),
            now=stringDate(now),
            owner_email=OWNER_EMAIL,
            provisioner=PROVISIONER_ID,
            scheduler="scheduler",
            service_name="test1",
            skip_docker="0",
            source_url=SOURCE_URL,
            task_group="group",
            task_index="project.fuzzing.orion.test1.push",
            worker=WORKER_TYPE,
            archs=str(["amd64"]),
        )
    )
    expected2["dependencies"].append(task1_id)
    assert task2 == expected2
    _, task3 = queue.createTask.call_args_list[2][0]
    expected3 = yaml_load(
        BUILD_TASK.substitute(
            clone_url="https://example.com",
            commit="commit",
            deadline=stringDate(now + DEADLINE),
            dockerfile="test2/Dockerfile",
            expires=stringDate(now + ARTIFACTS_EXPIRE),
            load_deps="1",
            max_run_time=int(MAX_RUN_TIME.total_seconds()),
            now=stringDate(now),
            owner_email=OWNER_EMAIL,
            provisioner=PROVISIONER_ID,
            scheduler="scheduler",
            service_name="test2",
            source_url=SOURCE_URL,
            task_group="group",
            worker=WORKER_TYPE,
            arch="amd64",
        )
    )
    expected3["dependencies"].append(task1_id)
    assert task3 == expected3


def test_cron_create_04(mocker: MockerFixture) -> None:
    """test no tasks are created for --dry-run"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    root = FIXTURES / "services03"
    repo = mocker.Mock(spec=GitRepo.from_existing(root))
    repo.path = root
    repo.git = mocker.Mock(return_value="\n".join(str(p) for p in root.glob("**/*")))
    repo.head.return_value = "commit"
    sched = CronScheduler(
        repo,
        "group",
        "scheduler",
        "secret",
        "https://example.com",
        "push",
        dry_run=True,
    )
    sched.services["test1"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 0
