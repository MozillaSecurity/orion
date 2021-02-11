# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Tests for Orion scheduler"""

from datetime import datetime
from pathlib import Path

import pytest
from taskcluster.utils import stringDate
from yaml import safe_load as yaml_load

from orion_decision import (
    ARTIFACTS_EXPIRE,
    DEADLINE,
    MAX_RUN_TIME,
    OWNER_EMAIL,
    PROVISIONER_ID,
    SCHEDULER_ID,
    SOURCE_URL,
    WORKER_TYPE,
)
from orion_decision.git import GithubEvent
from orion_decision.scheduler import BUILD_TASK, PUSH_TASK, TEST_TASK, Scheduler

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
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
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
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.commit_message = ""
    evt.list_changed_paths.return_value = [root / "recipes" / "linux" / "install.sh"]
    sched = Scheduler(evt, None, "group", "secret", "branch")
    sched.mark_services_for_rebuild()
    assert evt.list_changed_paths.call_count == 1
    assert sched.services["test1"].dirty
    assert sched.services["test2"].dirty
    assert not sched.services["test3"].dirty
    assert sched.services["test4"].dirty
    assert not sched.services["test5"].dirty
    assert not sched.services["test6"].dirty
    assert not sched.services["test7"].dirty


def test_mark_rebuild_03(mocker):
    """test that "/force-rebuild=svc" marks some services dirty"""
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.commit_message = "/force-rebuild=test3,test6"
    evt.list_changed_paths.return_value = [root / "recipes" / "linux" / "install.sh"]
    sched = Scheduler(evt, None, "group", "secret", "branch")
    sched.mark_services_for_rebuild()
    assert evt.list_changed_paths.call_count == 1
    assert sched.services["test1"].dirty
    assert sched.services["test2"].dirty
    assert sched.services["test3"].dirty
    assert sched.services["test4"].dirty
    assert not sched.services["test5"].dirty
    assert sched.services["test6"].dirty
    assert not sched.services["test7"].dirty


def test_create_01(mocker):
    """test no task creation"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.utcnow()
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
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
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.commit = "commit"
    evt.branch = "main"
    evt.clone_url = "https://example.com"
    evt.pull_request = None
    sched = Scheduler(evt, now, "group", "secret", "push")
    sched.services["test1"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 1
    _, task = queue.createTask.call_args.args
    assert task == yaml_load(
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
            route="index.project.fuzzing.orion.test1.main",
            scheduler=SCHEDULER_ID,
            service_name="test1",
            source_url=SOURCE_URL,
            task_group="group",
            worker=WORKER_TYPE,
        )
    )


def test_create_03(mocker):
    """test push task creation"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.utcnow()
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
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
            route="index.project.fuzzing.orion.test1.push",
            scheduler=SCHEDULER_ID,
            service_name="test1",
            source_url=SOURCE_URL,
            task_group="group",
            worker=WORKER_TYPE,
        )
    )
    _, push_task = queue.createTask.call_args_list[1].args
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
            scheduler=SCHEDULER_ID,
            service_name="test1",
            source_url=SOURCE_URL,
            task_group="group",
            worker=WORKER_TYPE,
        )
    )
    push_expected["dependencies"].append(build_task_id)
    assert push_task == push_expected


def test_create_04(mocker):
    """test dependent tasks creation"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.utcnow()
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
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
            route="index.project.fuzzing.orion.test1.main",
            scheduler=SCHEDULER_ID,
            service_name="test1",
            source_url=SOURCE_URL,
            task_group="group",
            worker=WORKER_TYPE,
        )
    )
    _, task2 = queue.createTask.call_args_list[1].args
    expected2 = yaml_load(
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
            route="index.project.fuzzing.orion.test2.main",
            scheduler=SCHEDULER_ID,
            service_name="test2",
            source_url=SOURCE_URL,
            task_group="group",
            worker=WORKER_TYPE,
        )
    )
    expected2["dependencies"].append(task1_id)
    assert task2 == expected2


def test_create_05(mocker):
    """test no tasks are created for release event"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.utcnow()
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
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
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
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
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.commit = "commit"
    evt.branch = "push"
    evt.clone_url = "https://example.com"
    evt.pull_request = 1
    sched = Scheduler(evt, now, "group", "secret", "push")
    sched.services["test1"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 1
    _, task = queue.createTask.call_args.args
    assert task == yaml_load(
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
            route="index.project.fuzzing.orion.test1.pull_request.1",
            scheduler=SCHEDULER_ID,
            service_name="test1",
            source_url=SOURCE_URL,
            task_group="group",
            worker=WORKER_TYPE,
        )
    )


@pytest.mark.parametrize(
    "ci1_dirty,svc1_dirty,svc2_dirty,expected_image",
    [
        (True, True, False, {"type": "task-image", "path": "public/testci1.tar.zst"}),
        (
            False,
            True,
            False,
            {
                "type": "indexed-image",
                "namespace": "project.fuzzing.orion.testci1.push",
                "path": "public/testci1.tar.zst",
            },
        ),
        (False, False, True, "python:latest"),
    ],
)
def test_create_08(mocker, ci1_dirty, svc1_dirty, svc2_dirty, expected_image):
    """test "test" tasks creation with dirty ci image"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.utcnow()
    root = FIXTURES / "services06"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.commit = "commit"
    evt.branch = "main"
    evt.fetch_ref = "fetch"
    evt.clone_url = "https://example.com"
    evt.pull_request = None
    sched = Scheduler(evt, now, "group", "secret", "push")
    sched.services["testci1"].dirty = ci1_dirty
    sched.services["svc1"].dirty = svc1_dirty
    sched.services["svc2"].dirty = svc2_dirty
    sched.create_tasks()
    assert queue.createTask.call_count == 3 if ci1_dirty else 2
    call_idx = 0
    if ci1_dirty:
        task1_id, task1 = queue.createTask.call_args_list[call_idx].args
        call_idx += 1
        assert task1 == yaml_load(
            BUILD_TASK.substitute(
                clone_url="https://example.com",
                commit="commit",
                deadline=stringDate(now + DEADLINE),
                dockerfile="testci1/Dockerfile",
                expires=stringDate(now + ARTIFACTS_EXPIRE),
                load_deps="0",
                max_run_time=int(MAX_RUN_TIME.total_seconds()),
                now=stringDate(now),
                owner_email=OWNER_EMAIL,
                provisioner=PROVISIONER_ID,
                route="index.project.fuzzing.orion.testci1.main",
                scheduler=SCHEDULER_ID,
                service_name="testci1",
                source_url=SOURCE_URL,
                task_group="group",
                worker=WORKER_TYPE,
            )
        )
    svc = "svc1" if svc1_dirty else "svc2"
    expected2 = yaml_load(
        TEST_TASK.substitute(
            commit="commit",
            commit_url="https://example.com",
            deadline=stringDate(now + DEADLINE),
            dockerfile=f"{svc}/Dockerfile",
            expires=stringDate(now + ARTIFACTS_EXPIRE),
            max_run_time=int(MAX_RUN_TIME.total_seconds()),
            now=stringDate(now),
            owner_email=OWNER_EMAIL,
            provisioner=PROVISIONER_ID,
            route=f"index.project.fuzzing.orion.{svc}.main",
            scheduler=SCHEDULER_ID,
            service_name=svc,
            source_url=SOURCE_URL,
            task_group="group",
            test_name=f"{svc}test",
            worker=WORKER_TYPE,
        )
    )
    if ci1_dirty:
        expected_image["taskId"] = task1_id
        expected2["dependencies"].append(task1_id)
    expected2["payload"]["image"] = expected_image
    sched.services[svc].tests[0].update_task(
        expected2, "https://example.com", "fetch", "commit", svc
    )
    task2_id, task2 = queue.createTask.call_args_list[call_idx].args
    call_idx += 1
    assert task2 == expected2
    task3_id, task3 = queue.createTask.call_args_list[call_idx].args
    call_idx += 1
    expected3 = yaml_load(
        BUILD_TASK.substitute(
            clone_url="https://example.com",
            commit="commit",
            deadline=stringDate(now + DEADLINE),
            dockerfile=f"{svc}/Dockerfile",
            expires=stringDate(now + ARTIFACTS_EXPIRE),
            load_deps="0",
            max_run_time=int(MAX_RUN_TIME.total_seconds()),
            now=stringDate(now),
            owner_email=OWNER_EMAIL,
            provisioner=PROVISIONER_ID,
            route=f"index.project.fuzzing.orion.{svc}.main",
            scheduler=SCHEDULER_ID,
            service_name=svc,
            source_url=SOURCE_URL,
            task_group="group",
            worker=WORKER_TYPE,
        )
    )
    expected3["dependencies"].append(task2_id)
    assert task3 == expected3
