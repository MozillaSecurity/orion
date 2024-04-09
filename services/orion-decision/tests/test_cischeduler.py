# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Tests for Orion CI scheduler"""

from datetime import datetime
from json import dumps as json_dump
from pathlib import Path
from typing import Optional

import pytest
from pytest_mock import MockerFixture
from taskcluster.utils import stringDate
from yaml import safe_load as yaml_load

from orion_decision import DEADLINE, MAX_RUN_TIME, PROVISIONER_ID
from orion_decision.ci_matrix import (
    CIArtifact,
    CISecret,
    CISecretEnv,
    CISecretFile,
    CISecretKey,
    MatrixJob,
)
from orion_decision.ci_scheduler import TEMPLATES, WORKER_TYPES, CIScheduler
from orion_decision.git import GithubEvent

FIXTURES = (Path(__file__).parent / "fixtures").resolve()
pytestmark = pytest.mark.usefixtures("mock_ci_languages")


@pytest.mark.parametrize("commit_message", [None, "[skip ci]", "[skip tc]"])
def test_ci_main(mocker: MockerFixture, commit_message: Optional[str]) -> None:
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
    sched = create.call_args[0][0]
    assert args.dry_run == bool(commit_message)
    assert sched.dry_run == bool(commit_message)


def test_ci_create_01(mocker: MockerFixture) -> None:
    """test no CI task creation"""
    taskcluster = mocker.patch("orion_decision.ci_scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.utcnow()
    evt = mocker.Mock(
        branch="dev",
        event_type="push",
        spec=GithubEvent(),
    )
    evt.repo.refs.return_value = {}
    mocker.patch("orion_decision.ci_scheduler.CIMatrix", autospec=True)
    sched = CIScheduler("test", evt, now, "group", "scheduler", {})
    sched.create_tasks()
    assert queue.createTask.call_count == 0


@pytest.mark.parametrize("matrix_artifact", (None, "file", "dir"))
@pytest.mark.parametrize("job_artifact", (None, "file", "dir"))
@pytest.mark.parametrize("matrix_secret", (None, "env", "key", "deploy", "file"))
@pytest.mark.parametrize("job_secret", (None, "env", "key", "deploy", "file"))
@pytest.mark.parametrize("platform", ("linux", "windows", "macos"))
def test_ci_create_02(
    mocker: MockerFixture,
    platform: str,
    matrix_secret: Optional[str],
    job_secret: Optional[str],
    matrix_artifact: Optional[str],
    job_artifact: Optional[str],
) -> None:
    """test single stage CI task creation"""
    taskcluster = mocker.patch("orion_decision.ci_scheduler.Taskcluster", autospec=True)
    queue = mocker.Mock()
    index = mocker.Mock()
    index.findTask.return_value = {"taskId": "gw-task"}
    taskcluster.get_service.side_effect = lambda x: {"index": index, "queue": queue}[x]
    now = datetime.utcnow()
    evt = mocker.Mock(
        branch="dev",
        event_type="push",
        ssh_url="ssh://repo",
        http_url="test://repo",
        fetch_ref="fetchref",
        repo_slug="project/test",
        tag=None,
        commit="commit",
        user="testuser",
        spec=GithubEvent(),
    )
    evt.repo.refs.return_value = {}
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
    artifacts = []
    scopes = []
    clone_repo = evt.http_url

    def _create_secret(kind: str, tag: str) -> CISecret:
        nonlocal clone_repo
        sec: CISecret
        if kind == "env":
            sec = CISecretEnv(f"project/test/{tag}token", "TOKEN")
        elif kind == "deploy":
            clone_repo = evt.ssh_url
            sec = CISecretKey(f"project/test/{tag}key")
        elif kind == "key":
            sec = CISecretKey(f"project/test/{tag}key", hostname="host")
        elif kind == "file":
            sec = CISecretFile(f"project/test/{tag}cfg", "/cfg")
        else:
            assert False, f"unknown secret kind: {kind}"
        scopes.append(f"secrets:get:{sec.secret}")
        return sec

    def _create_artifact(kind: str, tag: str) -> CIArtifact:
        return CIArtifact(kind, f"path/to/{tag}{kind}", f"project/test/{tag}{kind}")

    if job_secret is not None:
        sec = _create_secret(job_secret, "job")
        job.secrets.append(sec)
    if matrix_secret is not None:
        sec = _create_secret(matrix_secret, "mx")
        secrets.append(sec)
    if job_artifact:
        art = _create_artifact(job_artifact, "job")
        job.artifacts.append(art)
    if matrix_artifact:
        art = _create_artifact(matrix_artifact, "mx")
        artifacts.append(art)
    mtx.return_value.secrets = secrets
    mtx.return_value.artifacts = artifacts
    sched = CIScheduler("test", evt, now, "group", "scheduler", {})
    sched.create_tasks()
    assert queue.createTask.call_count == 1
    _, task = queue.createTask.call_args[0]
    # add matrix secrets to `job`. this is different than how it's done in the
    # scheduler, but will have the same effect (and the scheduler is done with `job`)
    job.secrets.extend(secrets)
    job.artifacts.extend(artifacts)
    kwds = {
        "ci_job": json_dump(str(job)),
        "clone_repo": clone_repo,
        "deadline": stringDate(now + DEADLINE),
        "fetch_ref": evt.fetch_ref,
        "fetch_rev": evt.commit,
        "http_repo": evt.http_url,
        "max_run_time": int(MAX_RUN_TIME.total_seconds()),
        "name": job.name,
        "now": stringDate(now),
        "project": "test",
        "provisioner": PROVISIONER_ID,
        "scheduler": "scheduler",
        "task_group": "group",
        "user": evt.user,
        "worker": WORKER_TYPES[platform],
    }
    if platform == "linux":
        kwds["image"] = job.image
        for art_flag, art_lst in [
            (job_artifact, job.artifacts),
            (matrix_artifact, artifacts),
        ]:
            if art_flag is None:
                continue
            assert len(art_lst) >= 1
            exp_art = art_lst[0]
            assert exp_art.url in task["payload"]["artifacts"]
            tsk_art = task["payload"]["artifacts"].pop(exp_art.url)
            assert tsk_art["path"] == exp_art.src
    else:
        assert index.findTask.call_count == 1
        assert job.image in index.findTask.call_args[0][0]
        if platform == "windows":
            kwds["msys_task"] = "gw-task"
        else:
            kwds["homebrew_task"] = "gw-task"
        for art_flag, art_lst in [
            (job_artifact, job.artifacts),
            (matrix_artifact, artifacts),
        ]:
            if art_flag is None:
                continue
            assert len(art_lst) >= 1
            exp_art = art_lst[0]
            for idx, tsk_art in enumerate(task["payload"]["artifacts"]):
                if tsk_art["name"] == exp_art.url:
                    assert tsk_art["path"] == exp_art.src
                    del task["payload"]["artifacts"][idx]
                    break
            else:
                raise RuntimeError("artifact not found")
    expected = yaml_load(TEMPLATES[platform].substitute(**kwds))
    expected["requires"] = "all-resolved"
    expected["scopes"].extend(scopes)
    if matrix_secret is not None or job_secret is not None:
        expected["payload"].setdefault("features", {})
        expected["payload"]["features"]["taskclusterProxy"] = True
    assert set(task["scopes"]) == set(expected["scopes"])
    assert len(task["scopes"]) == len(expected["scopes"])
    task["scopes"] = expected["scopes"]
    assert task == expected
    assert all(sec.secret in task["payload"]["env"]["CI_JOB"] for sec in job.secrets)
    assert all(art.url in task["payload"]["env"]["CI_JOB"] for art in job.artifacts)


@pytest.mark.parametrize("previous_pass", [True, False])
def test_ci_create_03(mocker: MockerFixture, previous_pass: bool) -> None:
    """test two stage CI task creation"""
    taskcluster = mocker.patch("orion_decision.ci_scheduler.Taskcluster", autospec=True)
    queue = taskcluster.get_service.return_value
    now = datetime.utcnow()
    evt = mocker.Mock(
        branch="dev",
        event_type="push",
        http_url="test://repo",
        fetch_ref="fetchref",
        commit="commit",
        user="testuser",
        repo_slug="project/test",
        tag=None,
        spec=GithubEvent(),
    )
    evt.repo.refs.return_value = {}
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
    sched = CIScheduler("test", evt, now, "group", "scheduler", {})
    sched.create_tasks()
    assert queue.createTask.call_count == 2
    task1_id, task1 = queue.createTask.call_args_list[0][0]
    kwds = {
        "ci_job": json_dump(str(job1)),
        "clone_repo": evt.http_url,
        "deadline": stringDate(now + DEADLINE),
        "fetch_ref": evt.fetch_ref,
        "fetch_rev": evt.commit,
        "http_repo": evt.http_url,
        "max_run_time": int(MAX_RUN_TIME.total_seconds()),
        "name": job1.name,
        "now": stringDate(now),
        "project": "test",
        "provisioner": PROVISIONER_ID,
        "scheduler": "scheduler",
        "task_group": "group",
        "user": evt.user,
        "worker": WORKER_TYPES[job1.platform],
    }
    kwds["image"] = job1.image
    expected = yaml_load(TEMPLATES[job1.platform].substitute(**kwds))
    expected["requires"] = "all-resolved"
    assert task1 == expected

    _, task2 = queue.createTask.call_args_list[1][0]
    kwds["ci_job"] = json_dump(str(job2))
    kwds["image"] = job2.image
    kwds["name"] = job2.name
    kwds["worker"] = WORKER_TYPES[job2.platform]
    expected = yaml_load(TEMPLATES[job2.platform].substitute(**kwds))
    if not previous_pass:
        expected["requires"] = "all-resolved"
    expected["dependencies"].append(task1_id)
    assert task2 == expected


@pytest.mark.parametrize("branch, tasks", [("dev", 0), ("main", 1), ("master", 1)])
def test_ci_create_04(mocker: MockerFixture, branch: str, tasks: int) -> None:
    """test PR push task skipped"""
    taskcluster = mocker.patch("orion_decision.ci_scheduler.Taskcluster", autospec=True)
    queue = mocker.Mock()
    index = mocker.Mock()
    index.findTask.return_value = {"taskId": "msys-task"}
    taskcluster.get_service.side_effect = lambda x: {"index": index, "queue": queue}[x]
    now = datetime.utcnow()
    evt = mocker.Mock(
        branch=branch,
        event_type="push",
        ssh_url="ssh://repo",
        http_url="test://repo",
        fetch_ref="fetchref",
        repo_slug="project/test",
        tag=None,
        commit="commit",
        user="testuser",
        spec=GithubEvent(),
    )
    evt.repo.refs.return_value = {"HEAD": "commit", "refs/pull/1/head": "commit"}
    mtx = mocker.patch("orion_decision.ci_scheduler.CIMatrix", autospec=True)
    job = MatrixJob(
        name="testjob",
        language="python",
        version="3.7",
        platform="linux",
        env={},
        script=["test"],
    )
    mtx.return_value.jobs = [job]
    mtx.return_value.secrets = []
    sched = CIScheduler("test", evt, now, "group", "scheduler", {})
    sched.create_tasks()
    assert queue.createTask.call_count == tasks
