# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Tests for Orion CI scheduler"""

from datetime import datetime
from pathlib import Path

import pytest
from taskcluster.utils import stringDate
from yaml import safe_load as yaml_load

from orion_decision import DEADLINE, MAX_RUN_TIME, PROVISIONER_ID, SCHEDULER_ID
from orion_decision.ci_matrix import CISecretEnv, CISecretFile, CISecretKey, MatrixJob
from orion_decision.ci_scheduler import TEMPLATES, WORKER_TYPES, CIScheduler
from orion_decision.git import GithubEvent

FIXTURES = (Path(__file__).parent / "fixtures").resolve()
pytestmark = pytest.mark.usefixtures("mock_ci_languages")


@pytest.mark.parametrize("commit_message", [None, "[skip ci]", "[skip tc]"])
def test_ci_main(mocker, commit_message):
    """test CI scheduler main"""
    evt = mocker.patch("orion_decision.ci_scheduler.GithubEvent", autospec=True)
    mtx = mocker.patch("orion_decision.ci_scheduler.CIMatrix", autospec=True)
    create = mocker.patch.object(CIScheduler, "create_tasks", autospec=True)
    if commit_message is not None:
        evt.from_taskcluster.return_value.commit_message = commit_message
    args = mocker.Mock(dry_run=False)
    assert CIScheduler.main(args) == 0
    assert evt.from_taskcluster.call_count == 1
    assert evt.from_taskcluster.return_value.cleanup.call_count == 1
    assert mtx.call_count == 1
    assert create.call_count == 1
    # get the scheduler instance from create call args
    sched = create.call_args.args[0]
    assert args.dry_run == bool(commit_message)
    assert sched.dry_run == bool(commit_message)


def test_ci_create_01(mocker):
    """test no CI task creation"""
    taskcluster = mocker.patch("orion_decision.ci_scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.utcnow()
    evt = mocker.Mock(
        branch="dev",
        event_type="push",
        spec=GithubEvent(),
    )
    mocker.patch("orion_decision.ci_scheduler.CIMatrix", autospec=True)
    sched = CIScheduler("test", evt, now, "group", "matrix")
    sched.create_tasks()
    assert queue.createTask.call_count == 0


@pytest.mark.parametrize(
    "platform, secret",
    [
        ("linux", None),
        ("windows", None),
        ("linux", "env"),
        ("linux", "key"),
        ("linux", "deploy"),
        ("linux", "file"),
    ],
)
def test_ci_create_02(mocker, platform, secret):
    """test single stage CI task creation"""
    taskcluster = mocker.patch("orion_decision.ci_scheduler.Taskcluster", autospec=True)
    queue = mocker.Mock()
    index = mocker.Mock()
    index.findTask.return_value = {"taskId": "msys-task"}
    taskcluster.get_service.side_effect = lambda x: {"index": index, "queue": queue}[x]
    now = datetime.utcnow()
    evt = mocker.Mock(
        branch="dev",
        event_type="push",
        ssh_repo="ssh://repo",
        http_repo="test://repo",
        fetch_ref="fetchref",
        commit="commit",
        user="testuser",
        spec=GithubEvent(),
    )
    mtx = mocker.patch("orion_decision.ci_scheduler.CIMatrix", autospec=True)
    job = MatrixJob(
        name="testjob",
        language="python",
        version="3.7",
        platform=platform,
        env={},
        script=["test"],
    )
    mtx.return_value.jobs = [job]
    secrets = []
    scopes = []
    clone_repo = evt.http_repo
    if secret is not None:
        if secret == "env":
            sec = CISecretEnv("project/test/token", "TOKEN")
        elif secret == "deploy":
            clone_repo = evt.ssh_repo
            sec = CISecretKey("project/test/key")
        elif secret == "key":
            sec = CISecretKey("project/test/key", hostname="host")
        elif secret == "file":
            sec = CISecretFile("project/test/cfg", "/cfg")
        secrets.append(sec)
        scopes.append(f"secrets:get:{sec.secret}")
    mtx.return_value.secrets = secrets
    sched = CIScheduler("test", evt, now, "group", "matrix")
    sched.create_tasks()
    assert queue.createTask.call_count == 1
    _, task = queue.createTask.call_args.args
    kwds = {
        "ci_job": str(job),
        "clone_repo": clone_repo,
        "deadline": stringDate(now + DEADLINE),
        "fetch_ref": evt.fetch_ref,
        "fetch_rev": evt.commit,
        "http_repo": evt.http_repo,
        "max_run_time": int(MAX_RUN_TIME.total_seconds()),
        "name": job.name,
        "now": stringDate(now),
        "project": "test",
        "provisioner": PROVISIONER_ID,
        "scheduler": SCHEDULER_ID,
        "task_group": "group",
        "user": evt.user,
        "worker": WORKER_TYPES[platform],
    }
    if platform == "linux":
        kwds["image"] = job.image
    else:
        assert index.findTask.call_count == 1
        assert job.image in index.findTask.call_args.args[0]
        kwds["msys_task"] = "msys-task"
    expected = yaml_load(TEMPLATES[platform].substitute(**kwds))
    expected["requires"] = "all-resolved"
    expected["scopes"].extend(scopes)
    if secret is not None:
        expected["payload"].setdefault("features", {})
        expected["payload"]["features"]["taskclusterProxy"] = True
    assert task == expected


@pytest.mark.parametrize("previous_pass", [True, False])
def test_ci_create_03(mocker, previous_pass):
    """test two stage CI task creation"""
    taskcluster = mocker.patch("orion_decision.ci_scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.utcnow()
    evt = mocker.Mock(
        branch="dev",
        event_type="push",
        http_repo="test://repo",
        fetch_ref="fetchref",
        commit="commit",
        user="testuser",
        spec=GithubEvent(),
    )
    mtx = mocker.patch("orion_decision.ci_scheduler.CIMatrix", autospec=True)
    job1 = MatrixJob(
        name="testjob1",
        language="python",
        version="3.7",
        platform="linux",
        env={},
        script=["test"],
    )
    job2 = MatrixJob(
        name="testjob2",
        language="python",
        version="3.7",
        platform=job1.platform,
        env={},
        script=["test"],
        stage=2,
        previous_pass=previous_pass,
    )
    mtx.return_value.jobs = [job1, job2]
    mtx.return_value.secrets = []
    sched = CIScheduler("test", evt, now, "group", "matrix")
    sched.create_tasks()
    assert queue.createTask.call_count == 2
    task1_id, task1 = queue.createTask.call_args_list[0].args
    kwds = {
        "ci_job": str(job1),
        "clone_repo": evt.http_repo,
        "deadline": stringDate(now + DEADLINE),
        "fetch_ref": evt.fetch_ref,
        "fetch_rev": evt.commit,
        "http_repo": evt.http_repo,
        "max_run_time": int(MAX_RUN_TIME.total_seconds()),
        "name": job1.name,
        "now": stringDate(now),
        "project": "test",
        "provisioner": PROVISIONER_ID,
        "scheduler": SCHEDULER_ID,
        "task_group": "group",
        "user": evt.user,
        "worker": WORKER_TYPES[job1.platform],
    }
    kwds["image"] = job1.image
    expected = yaml_load(TEMPLATES[job1.platform].substitute(**kwds))
    expected["requires"] = "all-resolved"
    assert task1 == expected

    _, task2 = queue.createTask.call_args_list[1].args
    kwds["ci_job"] = str(job2)
    kwds["image"] = job2.image
    kwds["name"] = job2.name
    kwds["worker"] = WORKER_TYPES[job2.platform]
    expected = yaml_load(TEMPLATES[job2.platform].substitute(**kwds))
    if not previous_pass:
        expected["requires"] = "all-resolved"
    expected["dependencies"].append(task1_id)
    assert task2 == expected
