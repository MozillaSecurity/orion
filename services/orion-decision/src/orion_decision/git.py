# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Git/Github utilities for Orion tasks"""
from logging import getLogger
from pathlib import Path
from shutil import rmtree
from subprocess import CalledProcessError, run
from tempfile import mkdtemp
from time import sleep

LOG = getLogger(__name__)
RETRY_SLEEP = 30
RETRIES = 10


class GitRepo:
    """A git repository.

    Attributes:
        path (Path): The location where the repository is cloned.
    """

    def __init__(self, clone_url, clone_ref, commit, _clone=True):
        """Initialize a GitRepo instance.

        Arguments:
            clone_url (str): The location to clone the repository from.
            clone_ref (str): The reference to fetch. (eg. branch).
            commit (str): Commit to checkout (must be `FETCH_HEAD` or an ancestor).
        """
        self._cloned = _clone
        if _clone:
            self.path = Path(mkdtemp(prefix="decision-repo-"))
            LOG.debug("created git repo tmp folder: %s", self.path)
            self._clone(clone_url, clone_ref, commit)
        else:
            self.path = Path(clone_url)
            LOG.debug("using existing git repo: %s", self.path)
            self.git("show", "--quiet")  # assert that path is valid

    @classmethod
    def from_existing(cls, path):
        """Initialize a GitRepo instance to access a local repository directly.

        Arguments:
            path (Path): The location of the git repository.

        Returns:
            GitRepo: Object for direct access to a local git repo (not a copy!)
        """
        return cls(path, None, None, _clone=False)

    def git(self, *args, tries=1):
        """Call a git command in the cloned repository.

        If tries is specified, the command will be retried on failure,
        with a 30s sleep between tries.

        Arguments:
            *args (str): The git command line to run (eg. `git("commit", "-a")`
            tries (int): Number of times to retry the git call.

        Raises:
            CalledProcessError: The git command failed.

        Returns:
            str: stdout returned by the process.
        """
        LOG.debug("calling: git %s", " ".join(str(arg) for arg in args))
        for _ in range(tries - 1):
            result = run(("git",) + args, capture_output=True, cwd=self.path, text=True)
            if result.returncode == 0:
                return result.stdout
            LOG.warning(
                "`git %s` returned %d, waiting %ds before retry...",
                " ".join(str(arg) for arg in args),
                result.returncode,
                RETRY_SLEEP,
            )
            sleep(RETRY_SLEEP)
        try:
            return run(
                ("git",) + args,
                check=True,
                capture_output=True,
                cwd=self.path,
                text=True,
            ).stdout
        except CalledProcessError as exc:
            LOG.error("git command returned error:\n%s", exc.stderr)
            raise

    def _clone(self, clone_url, clone_ref, commit):
        self.git("init")
        self.git("remote", "add", "origin", clone_url)
        self.git("fetch", "-q", "origin", clone_ref, tries=RETRIES)
        self.git("-c", "advice.detachedHead=false", "checkout", commit)

    def cleanup(self):
        """Clean up any resources held by this instance.

        Returns:
            None
        """
        if self._cloned and self.path is not None:
            rmtree(self.path)
        self.path = None

    def message(self, commit):
        """Get the commit message for a given commit.

        Arguments:
            commit (str): The commit to look up.

        Returns:
            str: The commit message (including headers).
        """
        return self.git("show", "--shortstat", commit)


class GithubEvent:
    """Something that happened on Github which caused this decision to be run.

    Attributes:
        branch (str): Name of the branch (push), target branch (PR), or tag (release).
        commit (str): The commit HEAD for this build.
        commit_message (str): Commit subject and body.
        commit_range (list(str)): Range of commits included in push or PR.
        event_type (str): One of "push", "pull_request", "release".
        pull_request (int or None): PR number (or None if not a PR).
        pr_branch (str or None): Name of the branch where PR is from (or None).
        pr_slug (str or None): Slug (`owner_name/repo_name`) where the PR is from.
        repo (GitRepo): Cloned git repository.
        repo_slug (str): Slug for the current repo (`owner_name/repo_name`).
        tag (str or None): Git tag for release event (or None).
        fetch_ref (str): Git reference to fetch
    """

    def __init__(self):
        """Create an unpopulated GithubEvent."""
        self.branch = None
        self.commit = None
        self.commit_message = None
        self.commit_range = None
        self.event_type = None
        self.pull_request = None
        self.pr_branch = None
        self.pr_slug = None
        self.repo_slug = None
        self.tag = None
        self.repo = None
        self.fetch_ref = None

    def cleanup(self):
        """Cleanup resources held by this instance.

        Returns:
            None
        """
        if self.repo is not None:
            self.repo.cleanup()

    @property
    def clone_url(self):
        """Calculate the URL for cloning this repository.

        Returns:
            str: The clone URL for this repository.
        """
        return f"https://github.com/{self.repo_slug}.git"

    @classmethod
    def from_taskcluster(cls, action, event):
        """Initialize the GithubEvent from Taskcluster context variables.

        Arguments:
            action (str): The Github action string from Taskcluster
                (one of "github-push", "github-pull-request", "github-release").
            event (dict): The raw Github Webhook event object.
                ref: https://docs.github.com/en/free-pro-team@latest/developers
                     /webhooks-and-events/webhook-events-and-payloads

        Returns:
            GithubEvent: Object describing the Github Event we're responding to.
        """
        self = cls()
        self.event_type = {
            "github-push": "push",
            "github-pull-request": "pull_request",
            "github-release": "release",
        }[action]
        self.repo_slug = event["repository"]["full_name"]
        if self.event_type == "pull_request":
            self.pull_request = event["number"]
            self.pr_branch = event["pull_request"]["head"]["ref"]
            self.pr_slug = event["pull_request"]["head"]["repo"]["full_name"]
            self.branch = event["pull_request"]["base"]["ref"]
            self.commit = event["pull_request"]["head"]["sha"]
            self.commit_range = f"{event['pull_request']['base']['sha']}..{self.commit}"
            self.fetch_ref = self.commit
        elif self.event_type == "release":
            self.tag = event["release"]["tag_name"]
            self.branch = self.tag
            self.commit = self.tag
            self.commit_range = f"{self.tag}^..{self.tag}"
            self.fetch_ref = f"refs/tags/{self.tag}:refs/tags/{self.tag}"
        else:
            # Strip ref branch prefix
            branch = event["ref"]
            if branch.startswith("refs/heads/"):
                branch = branch.split("/", 2)[2]
            self.branch = branch
            self.commit = event["after"]
            if set(event["before"]) == {"0"}:
                # for a new branch, we aren't directly told where the branch came from
                # use the commit prior to the first commit in the push instead
                self.commit_range = f"{event['commits'][0]['id']}^..{event['after']}"
            else:
                self.commit_range = f"{event['before']}..{event['after']}"
            self.fetch_ref = event["after"]
        self.repo = GitRepo(self.clone_url, self.fetch_ref, self.commit)

        # fetch both sides of the commit range
        before, _ = self.commit_range.split("..")
        self.repo.git("fetch", "-q", "origin", before, tries=RETRIES)

        self.commit_message = self.repo.message(self.commit_range)
        return self

    def list_changed_paths(self):
        """Calculate paths that were changed in the commit range.

        Arguments:
            commit_range (str): Commit range in the form: "before_sha..after_sha"

        Yields:
            Path: files changed by a commit range
        """
        changed = self.repo.git("diff", "--name-only", self.commit_range)
        for line in set(changed.splitlines()):
            LOG.info("Path changed in %s: %s", self.commit_range, line)
            yield self.repo.path / line
