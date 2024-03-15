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
from typing import Any, Dict, Generator, Optional, Union

LOG = getLogger(__name__)
RETRY_SLEEP = 30
RETRIES = 10

GIT_EVENT_TYPES = {
    "github-push": "push",
    "github-pull-request": "pull_request",
    "github-release": "release",
}


class GitRepo:
    """A git repository.

    Attributes:
        path: The location where the repository is cloned.
    """

    __slots__ = ("path", "_cloned")

    def __init__(
        self,
        clone_url: Union[Path, str],
        clone_ref: Optional[str],
        commit: Optional[str],
        _clone: bool = True,
    ) -> None:
        """Initialize a GitRepo instance.

        Arguments:
            clone_url: The location to clone the repository from.
            clone_ref: The reference to fetch. (eg. branch).
            commit: Commit to checkout (must be `FETCH_HEAD` or an ancestor).
        """
        self._cloned = _clone
        self.path: Optional[Path]
        if _clone:
            self.path = Path(mkdtemp(prefix="decision-repo-"))
            LOG.debug("created git repo tmp folder: %s", self.path)
            assert clone_ref is not None
            assert commit is not None
            self._clone(clone_url, clone_ref, commit)
        else:
            self.path = Path(clone_url)
            LOG.debug("using existing git repo: %s", self.path)
            self.git("show", "--quiet")  # assert that path is valid

    def refs(self) -> Dict[str, str]:
        """Get the list of refs available with associated commits.

        Returns:
            dictionary mapping ref name to commit hash.
        """
        result = {}
        for entry in self.git("ls-remote", "--quiet").splitlines():
            commit, ref = entry.split()
            result[ref] = commit
        return result

    def head(self) -> str:
        """Get the commit ref of HEAD.

        Returns:
            commit ref of HEAD as str
        """
        return self.git("show-ref", "--head", "HEAD").split()[0]

    @classmethod
    def from_existing(cls, path: Path) -> "GitRepo":
        """Initialize a GitRepo instance to access a local repository directly.

        Arguments:
            path: The location of the git repository.

        Returns:
            Object for direct access to a local git repo (not a copy!)
        """
        return cls(path, None, None, _clone=False)

    def git(self, *args: Union[Path, str], tries: int = 1) -> str:
        """Call a git command in the cloned repository.

        If tries is specified, the command will be retried on failure,
        with a 30s sleep between tries.

        Arguments:
            *args: The git command line to run (eg. `git("commit", "-a")`
            tries: Number of times to retry the git call.

        Raises:
            CalledProcessError: The git command failed.

        Returns:
            stdout returned by the process.
        """
        LOG.debug("calling: git %s", " ".join(str(arg) for arg in args))
        for _ in range(tries - 1):
            result = run(
                ("git", *args),
                capture_output=True,
                cwd=self.path,
                text=True,
            )
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
                ("git", *args),
                check=True,
                capture_output=True,
                cwd=self.path,
                text=True,
            ).stdout
        except CalledProcessError as exc:
            LOG.error("git command returned error:\n%s", exc.stderr)
            raise

    def _clone(self, clone_url: Union[Path, str], clone_ref: str, commit: str) -> None:
        self.git("init")
        self.git("remote", "add", "origin", clone_url)
        self.git("fetch", "-t", "-q", "origin", clone_ref, tries=RETRIES)
        self.git("-c", "advice.detachedHead=false", "checkout", commit)

    def cleanup(self) -> None:
        """Clean up any resources held by this instance."""
        if self._cloned and self.path is not None:
            rmtree(self.path)
        self.path = None

    def message(self, commit: str) -> str:
        """Get the commit message for a given commit.

        Arguments:
            commit: The commit to look up.

        Returns:
            The commit message (including headers).
        """
        return self.git("show", "--shortstat", commit)


class GithubEvent:
    """Something that happened on Github which caused this decision to be run.

    Attributes:
        branch: Name of the branch (push), target branch (PR), or tag (release).
        commit: The commit HEAD for this build.
        commit_message: Commit subject and body.
        commit_range: Range of commits included in push or PR.
        event_type: One of "push", "pull_request", "release".
        pull_request: PR number (or None if not a PR).
        pr_branch: Name of the branch where PR is from (or None).
        pr_slug: Slug (`owner_name/repo_name`) where the PR is from.
        repo: Cloned git repository.
        repo_slug: Slug for the current repo (`owner_name/repo_name`).
        tag: Git tag for release event (or None).
        fetch_ref: Git reference to fetch
        user: User that initiated this event.
    """

    def __init__(self) -> None:
        """Create an unpopulated GithubEvent."""
        self.branch: Optional[str] = None
        self.commit: Optional[str] = None
        self.commit_message: Optional[str] = None
        self.commit_range: Optional[str] = None
        self.event_type: Optional[str] = None
        self.pull_request: Optional[int] = None
        self.pr_branch: Optional[str] = None
        self.pr_slug: Optional[str] = None
        self.repo_slug: Optional[str] = None
        self.tag: Optional[str] = None
        self.repo: Optional[GitRepo] = None
        self.fetch_ref: Optional[str] = None
        self.user: Optional[str] = None

    def cleanup(self) -> None:
        """Cleanup resources held by this instance."""
        if self.repo is not None:
            self.repo.cleanup()

    @property
    def ssh_url(self) -> str:
        """Calculate the URL for cloning this repository via ssh.

        Returns:
            The clone URL for this repository.
        """
        return f"git@github.com:{self.repo_slug}"

    @property
    def http_url(self) -> str:
        """Calculate the URL for cloning this repository via http.

        Returns:
            The clone URL for this repository.
        """
        return f"https://github.com/{self.repo_slug}"

    @classmethod
    def from_taskcluster(
        cls, action: str, event: Dict[str, Any], clone_secret: Optional[str] = None
    ) -> "GithubEvent":
        """Initialize the GithubEvent from Taskcluster context variables.

        Arguments:
            action: The Github action string from Taskcluster
                (one of "github-push", "github-pull-request", "github-release").
            event: The raw Github Webhook event object.
                ref: https://docs.github.com/en/free-pro-team@latest/developers
                     /webhooks-and-events/webhook-events-and-payloads
            clone_secret: Taskcluster secret path used to fetch clone ssh key.

        Returns:
            Object describing the Github Event we're responding to.
        """
        self = cls()
        self.user = event["sender"]["login"]
        self.event_type = GIT_EVENT_TYPES[action]
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
            self.fetch_ref = f"refs/tags/{self.tag}:refs/tags/{self.tag}"
        else:
            # Strip ref branch prefix
            branch = event["ref"]
            if branch.startswith("refs/heads/"):
                branch = branch.split("/", 2)[2]
            self.branch = branch
            self.commit = event["after"]
            # for a new branch, we aren't directly told where the branch came from
            if set(event["before"]) != {"0"}:
                self.commit_range = f"{event['before']}..{event['after']}"
            self.fetch_ref = event["after"]
        if clone_secret:
            clone_url = self.ssh_url
        else:
            clone_url = self.http_url
        self.repo = GitRepo(clone_url, self.fetch_ref, self.commit)

        # fetch both sides of the commit range
        if self.commit_range is not None:
            before, _ = self.commit_range.split("..")
            if "^" not in before:
                self.repo.git("fetch", "-q", "origin", before, tries=RETRIES)

        self.commit_message = self.repo.message(str(self.commit_range or self.commit))
        return self

    def list_changed_paths(self) -> Generator[Path, None, None]:
        """Calculate paths that were changed in the commit range.

        Yields:
            files changed by a commit range
        """
        if self.commit_range is None:
            # no way to know what has changed.. so list all files.
            assert self.repo is not None
            changed = self.repo.git("ls-files")
        else:
            assert self.repo is not None
            changed = self.repo.git("diff", "--name-only", self.commit_range)
        for line in set(changed.splitlines()):
            LOG.info("Path changed in %s: %s", self.commit_range, line)
            assert self.repo.path is not None
            yield self.repo.path / line
