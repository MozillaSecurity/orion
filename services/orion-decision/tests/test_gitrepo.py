# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Tests for GitRepo"""

from pathlib import Path
from tempfile import gettempdir
from subprocess import CalledProcessError
from unittest.mock import call

import pytest

from orion_decision.git import GitRepo, GithubEvent


FIXTURES = (Path(__file__).parent / "fixtures").resolve()


def test_cleanup():
    """test that repo is checked out in a temp folder and removed by cleanup"""
    repo = GitRepo(FIXTURES / "git01", "main", "FETCH_HEAD")
    try:
        repo_path = repo.path
        assert repo_path.is_dir()
        assert (repo_path / ".git").is_dir()
        assert Path(gettempdir()) in repo_path.parents
    finally:
        repo.cleanup()
    assert not repo_path.exists()
    assert repo.path is None


def test_message():
    """test that commit message is read"""
    repo = GitRepo(FIXTURES / "git01", "main", "FETCH_HEAD")
    try:
        assert "Test commit message" in repo.message("FETCH_HEAD")
    finally:
        repo.cleanup()


def test_retry(mocker):
    sleep = mocker.patch("orion_decision.git.sleep", autospec=True)
    with pytest.raises(CalledProcessError):
        GitRepo(FIXTURES / "git-noexist", "main", "FETCH_HEAD")
    assert sleep.call_count == 9


@pytest.mark.parametrize(
    "action, event, result, repo_args",
    [
        (
            "github-push",
            {
                "repository": {"full_name": "allizom/test"},
                "ref": "refs/heads/main",
                "after": "post",
                "before": "pre",
            },
            {
                "branch": "main",
                "commit": "post",
                "commit_message": "Test commit message",
                "commit_range": "pre..post",
                "event_type": "push",
                "pull_request": None,
                "pr_branch": None,
                "pr_slug": None,
                "repo_slug": "allizom/test",
                "tag": None,
            },
            call("https://github.com/allizom/test.git", "refs/heads/main", "post"),
        ),
        (
            "github-pull-request",
            {
                "repository": {"full_name": "allizom/test"},
                "number": 7,
                "pull_request": {
                    "base": {
                        "ref": "main",
                        "sha": "pre",
                    },
                    "head": {
                        "ref": "change",
                        "sha": "post",
                        "repo": {
                            "full_name": "user/test",
                        },
                    },
                },
            },
            {
                "branch": "main",
                "commit": "post",
                "commit_message": "Test commit message",
                "commit_range": "pre..post",
                "event_type": "pull_request",
                "pull_request": 7,
                "pr_branch": "change",
                "pr_slug": "user/test",
                "repo_slug": "allizom/test",
                "tag": None,
            },
            call("https://github.com/allizom/test.git", "pull/7/head", "post"),
        ),
        (
            "github-release",
            {
                "repository": {"full_name": "allizom/test"},
                "release": {"tag_name": "1.0"},
            },
            {
                "branch": "1.0",
                "commit": "1.0",
                "commit_message": "Test commit message",
                "commit_range": "1.0^..1.0",
                "event_type": "release",
                "pull_request": None,
                "pr_branch": None,
                "pr_slug": None,
                "repo_slug": "allizom/test",
                "tag": "1.0",
            },
            call(
                "https://github.com/allizom/test.git",
                "refs/tags/1.0:refs/tags/1.0",
                "1.0",
            ),
        ),
    ],
)
def test_github_tc(mocker, action, event, result, repo_args):
    """test github event parsing from taskcluster"""
    repo = mocker.patch("orion_decision.git.GitRepo")
    repo.return_value.message.return_value = "Test commit message"
    evt = GithubEvent.from_taskcluster(action, event)
    assert evt.repo is repo.return_value
    assert repo.call_args == repo_args
    assert repo.return_value.cleanup.call_count == 0
    evt.cleanup()
    assert repo.return_value.cleanup.call_count == 1
    for attr, value in result.items():
        assert getattr(evt, attr) == value


def test_github_changed(mocker):
    """test github lists changed files in commit range"""
    repo = GitRepo(FIXTURES / "git02", "main", "FETCH_HEAD")
    try:
        evt = GithubEvent()
        evt.repo = repo
        evt.commit_range = "HEAD^..HEAD"
        changed_paths = set(evt.list_changed_paths())
        assert changed_paths == {repo.path / "a.txt"}
    finally:
        repo.cleanup()