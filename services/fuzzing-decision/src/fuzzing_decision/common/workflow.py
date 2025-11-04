# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from time import sleep
from typing import Any

import yaml

from . import taskcluster

LOG = logging.getLogger(__name__)
RETRIES = 10
RETRY_SLEEP = 30


class Workflow:
    def __init__(self) -> None:
        taskcluster.auth()
        self.ssh_private_key: Path | None = None

    @property
    def in_taskcluster(self) -> bool:
        return "TASK_ID" in os.environ and "TASKCLUSTER_ROOT_URL" in os.environ

    def configure(
        self,
        local_path: Path | None = None,
        secret: str | None = None,
        fuzzing_git_repository: str | None = None,
        fuzzing_git_revision: str | None = None,
    ) -> dict[str, Any] | None:
        """Load configuration either from local file or Taskcluster secret"""

        if local_path is not None:
            assert local_path.is_file(), f"Missing configuration in {local_path}"
            config = yaml.safe_load(local_path.read_text())

        elif secret is not None:
            config = taskcluster.load_secrets(secret)

        else:
            return None

        assert isinstance(config, dict)
        if "community_config" not in config:
            config["community_config"] = {
                "url": "git@github.com:taskcluster/community-tc-config.git",
                "revision": "main",
            }

        # Use Github repo & revision from environment when specified
        if fuzzing_git_repository and fuzzing_git_revision:
            LOG.info(
                f"Use Fuzzing git repository from options: {fuzzing_git_repository} @ "
                f"{fuzzing_git_revision}"
            )
            config["fuzzing_config"] = {
                "url": fuzzing_git_repository,
                "revision": fuzzing_git_revision,
            }

        assert "fuzzing_config" in config, "Missing fuzzing_config"

        return config

    def clone(self, config: dict[str, str]) -> None:
        """Clone remote repositories according to current setup"""
        assert isinstance(config, dict)

        ssh_path = Path("~/.ssh").expanduser()
        ssh_path.mkdir(mode=0o700, exist_ok=True)
        ssh_path.chmod(0o700)
        hosts = ssh_path / "known_hosts"
        if hosts.is_file():
            hosts.chmod(0o600)

        # Setup ssh private key if any
        private_key = config.get("private_key")
        if private_key is not None:
            path = ssh_path / "id_rsa.decision"
            if path.exists():
                LOG.warning(f"Not overwriting pre-existing ssh key at {path}")
            else:
                with path.open("w", newline="\n") as key_fp:
                    key_fp.write(private_key)
                path.chmod(0o400)
                LOG.info("Installed ssh private key")
                self.ssh_private_key = path

    def git_clone(
        self,
        url: str | None = None,
        path: Path | None = None,
        revision: str | None = None,
        **kwargs: Any,
    ) -> Path:
        """Clone a configuration repository"""

        if path is not None:
            path = Path(path)
            # Use local path when available
            assert path.is_dir(), f"Invalid repo dir {path}"
            LOG.info(f"Using local configuration in {path}")
        elif url is not None:
            # Clone from remote repository
            path = Path(tempfile.mkdtemp(suffix=url[url.rindex("/") + 1 :]))

            # Clone the configuration repository
            if revision is None:
                revision = "master"
            LOG.info(f"Cloning {url} @ {revision}")
            cmd = ["git", "init", str(path)]
            subprocess.check_output(cmd)
            cmd = ["git", "remote", "add", "origin", url]
            subprocess.check_output(cmd, cwd=str(path))
            env = {}
            if self.ssh_private_key is not None:
                env["GIT_SSH_COMMAND"] = (
                    f"ssh -v -i '{self.ssh_private_key}' -o IdentitiesOnly=yes"
                )
            cmd = ["git", "fetch", "-q", "origin", revision]
            for _ in range(RETRIES - 1):
                result = subprocess.run(
                    cmd, cwd=str(path), env=env, stdout=subprocess.PIPE
                )
                if result.returncode == 0:
                    break
                LOG.warning(
                    "git fetch returned %d, retrying after %ds",
                    result.returncode,
                    RETRY_SLEEP,
                )
                sleep(RETRY_SLEEP)
            else:
                subprocess.check_output(cmd, cwd=str(path))
            cmd = ["git", "-c", "advice.detachedHead=false", "checkout", revision]
            subprocess.check_output(cmd, cwd=str(path))
            LOG.info(f"Using cloned config files in {path}")
        else:
            raise Exception("You need to specify a repo url or local path")

        return path
