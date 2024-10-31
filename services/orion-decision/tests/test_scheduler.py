# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Tests for Orion scheduler"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

import pytest
from freezegun import freeze_time
from pytest_mock import MockerFixture
from taskcluster.utils import stringDate
from yaml import safe_load as yaml_load

from orion_decision import (
    ARTIFACTS_EXPIRE,
    DEADLINE,
    MAX_RUN_TIME,
    OWNER_EMAIL,
    PROVISIONER_ID,
    SOURCE_URL,
    WORKER_TYPE,
    WORKER_TYPE_ARM64,
    WORKER_TYPE_BREW,
    WORKER_TYPE_MSYS,
)
from orion_decision.git import GithubEvent
from orion_decision.scheduler import (
    BUILD_TASK,
    COMBINE_TASK,
    HOMEBREW_TASK,
    MSYS_TASK,
    PUSH_TASK,
    RECIPE_TEST_TASK,
    TEST_TASK,
    Scheduler,
)

FIXTURES = (Path(__file__).parent / "fixtures").resolve()


def test_main(mocker: MockerFixture) -> None:
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


def test_mark_rebuild_01(mocker: MockerFixture) -> None:
    """test that "/force-rebuild" marks all services dirty"""
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.commit_message = "/force-rebuild"
    sched = Scheduler(evt, "group", "scheduler", "secret", "branch")
    sched.mark_services_for_rebuild()
    for svc in sched.services.values():
        assert svc.dirty
    assert evt.list_changed_paths.call_count == 0


def test_mark_rebuild_02(mocker: MockerFixture) -> None:
    """test that changed paths mark dependent services dirty"""
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.commit_message = ""
    evt.list_changed_paths.return_value = [root / "recipes" / "linux" / "install.sh"]
    sched = Scheduler(evt, "group", "scheduler", "secret", "branch")
    sched.mark_services_for_rebuild()
    assert evt.list_changed_paths.call_count == 1
    assert sched.services["test1"].dirty
    assert sched.services["test2"].dirty
    assert not sched.services["test3"].dirty
    assert sched.services["test4"].dirty
    assert not sched.services["test5"].dirty
    assert not sched.services["test6"].dirty
    assert not sched.services["test7"].dirty


def test_mark_rebuild_03(mocker: MockerFixture) -> None:
    """test that "/force-rebuild=svc" marks some services dirty"""
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.commit_message = "/force-rebuild=test3,test6"
    evt.list_changed_paths.return_value = [root / "recipes" / "linux" / "install.sh"]
    sched = Scheduler(evt, "group", "scheduler", "secret", "branch")
    sched.mark_services_for_rebuild()
    assert evt.list_changed_paths.call_count == 1
    assert sched.services["test1"].dirty
    assert sched.services["test2"].dirty
    assert sched.services["test3"].dirty
    assert sched.services["test4"].dirty
    assert not sched.services["test5"].dirty
    assert sched.services["test6"].dirty
    assert not sched.services["test7"].dirty


def test_create_01(mocker: MockerFixture) -> None:
    """test no task creation"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    sched = Scheduler(evt, "group", "scheduler", "secret", "push")
    sched.create_tasks()
    assert queue.createTask.call_count == 0


@freeze_time()
def test_create_02(mocker: MockerFixture) -> None:
    """test non-push task creation"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.now(timezone.utc)
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.commit = "commit"
    evt.branch = "main"
    evt.http_url = "https://example.com"
    evt.pull_request = None
    sched = Scheduler(evt, "group", "scheduler", "secret", "push")
    sched.services["test1"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 1
    _, task = queue.createTask.call_args[0]
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
            scheduler="scheduler",
            service_name="test1",
            source_url=SOURCE_URL,
            task_group="group",
            worker=WORKER_TYPE,
            arch="amd64",
        )
    )


@freeze_time()
def test_create_03(mocker: MockerFixture) -> None:
    """test push task creation for single arch"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.now(timezone.utc)
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.repo.refs.return_value = {}
    evt.commit = "commit"
    evt.branch = "push"
    evt.event_type = "push"
    evt.http_url = "https://example.com"
    evt.pull_request = None
    sched = Scheduler(evt, "group", "scheduler", "secret", "push")
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
            archs=["amd64"],
        )
    )
    push_expected["dependencies"].append(build_task_id)
    assert push_task == push_expected


@freeze_time()
def test_create_04(mocker: MockerFixture) -> None:
    """test dependent tasks creation"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.now(timezone.utc)
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.commit = "commit"
    evt.branch = "main"
    evt.http_url = "https://example.com"
    evt.pull_request = None
    sched = Scheduler(evt, "group", "scheduler", "secret", "push")
    sched.services["test1"].dirty = True
    sched.services["test2"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 2
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
    expected2["dependencies"].append(task1_id)
    assert task2 == expected2


def test_create_05(mocker: MockerFixture) -> None:
    """test no tasks are created for release event"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.event_type = "release"
    sched = Scheduler(evt, "group", "scheduler", "secret", "push")
    sched.services["test1"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 0


def test_create_06(mocker: MockerFixture) -> None:
    """test no tasks are created for --dry-run"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.repo.refs.return_value = {}
    evt.event_type = "push"
    evt.commit = "commit"
    evt.branch = "push"
    evt.pull_request = None
    evt.http_url = "https://example.com"
    sched = Scheduler(evt, "group", "scheduler", "secret", "push", dry_run=True)
    sched.services["test1"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 0


@freeze_time()
def test_create_07(mocker: MockerFixture) -> None:
    """test PR doesn't create push task"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.now(timezone.utc)
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.commit = "commit"
    evt.branch = "push"
    evt.http_url = "https://example.com"
    evt.pull_request = 1
    sched = Scheduler(evt, "group", "scheduler", "secret", "push")
    sched.services["test1"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 1
    _, task = queue.createTask.call_args[0]
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
            scheduler="scheduler",
            service_name="test1",
            source_url=SOURCE_URL,
            task_group="group",
            worker=WORKER_TYPE,
            arch="amd64",
        )
    )


@freeze_time()
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
def test_create_08(
    mocker: MockerFixture,
    ci1_dirty: bool,
    svc1_dirty: bool,
    svc2_dirty: bool,
    expected_image: Dict[str, str],
) -> None:
    """test "test" tasks creation with dirty ci image"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.now(timezone.utc)
    root = FIXTURES / "services06"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.commit = "commit"
    evt.branch = "main"
    evt.fetch_ref = "fetch"
    evt.http_url = "https://example.com"
    evt.pull_request = None
    sched = Scheduler(evt, "group", "scheduler", "secret", "push")
    sched.services["testci1"].dirty = ci1_dirty
    sched.services["svc1"].dirty = svc1_dirty
    sched.services["svc2"].dirty = svc2_dirty
    sched.create_tasks()
    assert queue.createTask.call_count == 3 if ci1_dirty else 2
    call_idx = 0
    if ci1_dirty:
        task1_id, task1 = queue.createTask.call_args_list[call_idx][0]
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
                scheduler="scheduler",
                service_name="testci1",
                source_url=SOURCE_URL,
                task_group="group",
                worker=WORKER_TYPE,
                arch="amd64",
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
            scheduler="scheduler",
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
    task2_id, task2 = queue.createTask.call_args_list[call_idx][0]
    call_idx += 1
    assert task2 == expected2
    task3_id, task3 = queue.createTask.call_args_list[call_idx][0]
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
            scheduler="scheduler",
            service_name=svc,
            source_url=SOURCE_URL,
            task_group="group",
            worker=WORKER_TYPE,
            arch="amd64",
        )
    )
    expected3["dependencies"].append(task2_id)
    assert task3 == expected3


@freeze_time()
def test_create_09(mocker: MockerFixture) -> None:
    """test recipe test task creation"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.now(timezone.utc)
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.commit = "commit"
    evt.branch = "main"
    evt.http_url = "https://example.com"
    evt.pull_request = None
    sched = Scheduler(evt, "group", "scheduler", "secret", "push")
    sched.services["test5"].dirty = True
    sched.services["test6"].dirty = True
    sched.services.recipes["withdep.sh"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 3
    task1_id, task1 = queue.createTask.call_args_list[0][0]
    assert task1 == yaml_load(
        BUILD_TASK.substitute(
            clone_url="https://example.com",
            commit="commit",
            deadline=stringDate(now + DEADLINE),
            dockerfile="test5/Dockerfile",
            expires=stringDate(now + ARTIFACTS_EXPIRE),
            load_deps="0",
            max_run_time=int(MAX_RUN_TIME.total_seconds()),
            now=stringDate(now),
            owner_email=OWNER_EMAIL,
            provisioner=PROVISIONER_ID,
            scheduler="scheduler",
            service_name="test5",
            source_url=SOURCE_URL,
            task_group="group",
            worker=WORKER_TYPE,
            arch="amd64",
        )
    )
    task2_id, task2 = queue.createTask.call_args_list[1][0]
    expected2 = yaml_load(
        RECIPE_TEST_TASK.substitute(
            clone_url="https://example.com",
            commit="commit",
            deadline=stringDate(now + DEADLINE),
            dockerfile="services/test-recipes/Dockerfile",
            max_run_time=int(MAX_RUN_TIME.total_seconds()),
            now=stringDate(now),
            owner_email=OWNER_EMAIL,
            provisioner=PROVISIONER_ID,
            recipe_name="withdep.sh",
            scheduler="scheduler",
            source_url=SOURCE_URL,
            task_group="group",
            worker=WORKER_TYPE,
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
            dockerfile="test6/Dockerfile",
            expires=stringDate(now + ARTIFACTS_EXPIRE),
            load_deps="0",
            max_run_time=int(MAX_RUN_TIME.total_seconds()),
            now=stringDate(now),
            owner_email=OWNER_EMAIL,
            provisioner=PROVISIONER_ID,
            scheduler="scheduler",
            service_name="test6",
            source_url=SOURCE_URL,
            task_group="group",
            worker=WORKER_TYPE,
            arch="amd64",
        )
    )
    expected3["dependencies"].append(task2_id)
    assert task3 == expected3


@freeze_time()
def test_create_10(mocker: MockerFixture) -> None:
    """test msys task creation"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.now(timezone.utc)
    root = FIXTURES / "services11"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.commit = "commit"
    evt.branch = "main"
    evt.http_url = "https://example.com"
    evt.pull_request = None
    sched = Scheduler(evt, "group", "scheduler", "secret", "push")
    sched.services["msys-svc"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 1
    _, task = queue.createTask.call_args[0]
    assert task == yaml_load(
        MSYS_TASK.substitute(
            clone_url="https://example.com",
            commit="commit",
            deadline=stringDate(now + DEADLINE),
            expires=stringDate(now + ARTIFACTS_EXPIRE),
            max_run_time=int(MAX_RUN_TIME.total_seconds()),
            msys_base_url="msys.tar.xz",
            now=stringDate(now),
            owner_email=OWNER_EMAIL,
            provisioner=PROVISIONER_ID,
            scheduler="scheduler",
            setup_sh_path="test-msys/setup.sh",
            service_name="msys-svc",
            source_url=SOURCE_URL,
            task_group="group",
            worker=WORKER_TYPE_MSYS,
        )
    )


@freeze_time()
def test_create_11(mocker: MockerFixture) -> None:
    """test homebrew task creation"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.now(timezone.utc)
    root = FIXTURES / "services11"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.commit = "commit"
    evt.branch = "main"
    evt.http_url = "https://example.com"
    evt.pull_request = None
    sched = Scheduler(evt, "group", "scheduler", "secret", "push")
    sched.services["brew-svc"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 1
    _, task = queue.createTask.call_args[0]
    assert task == yaml_load(
        HOMEBREW_TASK.substitute(
            clone_url="https://example.com",
            commit="commit",
            deadline=stringDate(now + DEADLINE),
            expires=stringDate(now + ARTIFACTS_EXPIRE),
            homebrew_base_url="brew.tar.bz2",
            max_run_time=int(MAX_RUN_TIME.total_seconds()),
            now=stringDate(now),
            owner_email=OWNER_EMAIL,
            provisioner=PROVISIONER_ID,
            scheduler="scheduler",
            service_name="brew-svc",
            setup_sh_path="test-brew/setup.sh",
            source_url=SOURCE_URL,
            task_group="group",
            worker=WORKER_TYPE_BREW,
        )
    )


@freeze_time()
def test_create_12(mocker: MockerFixture) -> None:
    """test test task non-creation"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.now(timezone.utc)
    root = FIXTURES / "services11"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.commit = "commit"
    evt.branch = "main"
    evt.fetch_ref = "fetch"
    evt.http_url = "https://example.com"
    evt.pull_request = None
    sched = Scheduler(evt, "group", "scheduler", "secret", "push")
    sched.services["test-svc"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 1
    _, task = queue.createTask.call_args[0]
    expected = yaml_load(
        TEST_TASK.substitute(
            commit="commit",
            commit_url="https://example.com",
            deadline=stringDate(now + DEADLINE),
            dockerfile="Dockerfile",
            expires=stringDate(now + ARTIFACTS_EXPIRE),
            max_run_time=int(MAX_RUN_TIME.total_seconds()),
            now=stringDate(now),
            owner_email=OWNER_EMAIL,
            provisioner=PROVISIONER_ID,
            scheduler="scheduler",
            service_name="test-svc",
            source_url=SOURCE_URL,
            task_group="group",
            test_name="test",
            worker=WORKER_TYPE,
        )
    )
    expected["payload"]["image"] = "ci-py-38"
    sched.services["test-svc"].tests[0].update_task(
        expected, "https://example.com", "fetch", "commit", "test-only"
    )
    assert task == expected


@pytest.mark.parametrize("branch, tasks", [("dev", 0), ("main", 0), ("push", 2)])
def test_create_13(mocker: MockerFixture, branch: str, tasks: int) -> None:
    """test push in PR task creation skipped"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    root = FIXTURES / "services03"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.repo.refs.return_value = {"HEAD": "commit", "refs/pull/1/head": "commit"}
    evt.commit = "commit"
    evt.event_type = "push"
    evt.branch = branch
    evt.http_url = "https://example.com"
    evt.pull_request = None
    sched = Scheduler(evt, "group", "scheduler", "secret", "push")
    sched.services["test1"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == tasks


@freeze_time()
def test_create_14(mocker: MockerFixture) -> None:
    """test combine task creation"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.now(timezone.utc)
    root = FIXTURES / "services12"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.commit = "commit"
    evt.branch = "main"
    evt.http_url = "https://example.com"
    evt.pull_request = None
    sched = Scheduler(evt, "group", "scheduler", "secret", "push")
    sched.services["test1"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 3
    build_task1_id, build_task1 = queue.createTask.call_args_list[0][0]
    assert build_task1 == yaml_load(
        BUILD_TASK.substitute(
            clone_url="https://example.com",
            commit="commit",
            deadline=stringDate(now + DEADLINE),
            dockerfile="Dockerfile",
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
    build_task2_id, build_task2 = queue.createTask.call_args_list[1][0]
    assert build_task2 == yaml_load(
        BUILD_TASK.substitute(
            clone_url="https://example.com",
            commit="commit",
            deadline=stringDate(now + DEADLINE),
            dockerfile="Dockerfile",
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
            worker=WORKER_TYPE_ARM64,
            arch="arm64",
        )
    )
    _, combine_task = queue.createTask.call_args_list[2][0]
    combine_expected = yaml_load(
        COMBINE_TASK.substitute(
            clone_url="https://example.com",
            commit="commit",
            deadline=stringDate(now + DEADLINE),
            expires=stringDate(now + ARTIFACTS_EXPIRE),
            max_run_time=int(MAX_RUN_TIME.total_seconds()),
            now=stringDate(now),
            owner_email=OWNER_EMAIL,
            provisioner=PROVISIONER_ID,
            scheduler="scheduler",
            service_name="test1",
            source_url=SOURCE_URL,
            task_group="group",
            worker=WORKER_TYPE,
            archs=["amd64", "arm64"],
        )
    )
    combine_expected["dependencies"].append(build_task1_id)
    combine_expected["dependencies"].append(build_task2_id)
    assert combine_task == combine_expected


@freeze_time()
def test_create_15(mocker: MockerFixture) -> None:
    """test push task creation for multiple archs"""
    taskcluster = mocker.patch("orion_decision.scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.now(timezone.utc)
    root = FIXTURES / "services12"
    evt = mocker.Mock(spec=GithubEvent())
    evt.repo.path = root
    evt.repo.git = mocker.Mock(
        return_value="\n".join(str(p) for p in root.glob("**/*"))
    )
    evt.repo.refs.return_value = {}
    evt.commit = "commit"
    evt.branch = "push"
    evt.event_type = "push"
    evt.http_url = "https://example.com"
    evt.pull_request = None
    sched = Scheduler(evt, "group", "scheduler", "secret", "push")
    sched.services["test1"].dirty = True
    sched.create_tasks()
    assert queue.createTask.call_count == 4

    build_task_id, build_task = queue.createTask.call_args_list[0][0]
    build_task1_id, build_task1 = queue.createTask.call_args_list[0][0]
    assert build_task1 == yaml_load(
        BUILD_TASK.substitute(
            clone_url="https://example.com",
            commit="commit",
            deadline=stringDate(now + DEADLINE),
            dockerfile="Dockerfile",
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
    build_task2_id, build_task2 = queue.createTask.call_args_list[1][0]
    assert build_task2 == yaml_load(
        BUILD_TASK.substitute(
            clone_url="https://example.com",
            commit="commit",
            deadline=stringDate(now + DEADLINE),
            dockerfile="Dockerfile",
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
            worker=WORKER_TYPE_ARM64,
            arch="arm64",
        )
    )
    combine_task_id, combine_task = queue.createTask.call_args_list[2][0]
    combine_expected = yaml_load(
        COMBINE_TASK.substitute(
            clone_url="https://example.com",
            commit="commit",
            deadline=stringDate(now + DEADLINE),
            expires=stringDate(now + ARTIFACTS_EXPIRE),
            max_run_time=int(MAX_RUN_TIME.total_seconds()),
            now=stringDate(now),
            owner_email=OWNER_EMAIL,
            provisioner=PROVISIONER_ID,
            scheduler="scheduler",
            service_name="test1",
            source_url=SOURCE_URL,
            task_group="group",
            worker=WORKER_TYPE,
            archs=str(["amd64", "arm64"]),
        )
    )
    combine_expected["dependencies"].append(build_task1_id)
    combine_expected["dependencies"].append(build_task2_id)
    assert combine_task == combine_expected
    _, push_task = queue.createTask.call_args_list[3][0]
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
            archs=str(["amd64", "arm64"]),
        )
    )
    push_expected["dependencies"].append(combine_task_id)
    assert push_task == push_expected
