# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.


import logging
import os
import pathlib
import subprocess
import tempfile

import yaml

from . import taskcluster

LOG = logging.getLogger(__name__)


class Workflow:
    def __init__(self) -> None:
        taskcluster.auth()

    @property
    def in_taskcluster(self) -> bool:
        return "TASK_ID" in os.environ and "TASKCLUSTER_ROOT_URL" in os.environ

    def configure(
        self,
        local_path: pathlib.Path | None = None,
        secret: str | None = None,
        fuzzing_git_repository: str | None = None,
        fuzzing_git_revision: str | None = None,
    ):
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
                "url": "git@github.com:mozilla/community-tc-config.git"
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

        ssh_path = pathlib.Path("~/.ssh").expanduser()
        ssh_path.mkdir(mode=0o700, exist_ok=True)

        # Setup ssh private key if any
        private_key = config.get("private_key")
        if private_key is not None:
            path = ssh_path / "id_rsa"
            if path.exists():
                LOG.warning(f"Not overwriting pre-existing ssh key at {path}")
            else:
                with path.open("w", newline="\n") as key_fp:
                    key_fp.write(private_key)
                path.chmod(0o400)
                LOG.info("Installed ssh private key")

        with (ssh_path / "known_hosts").open("a") as hosts:
            subprocess.check_call(["ssh-keyscan", "github.com"], stdout=hosts)

    def git_clone(
        self,
        url: str | None = None,
        path: pathlib.Path | None = None,
        revision: str | None = None,
        **kwargs,
    ) -> pathlib.Path:
        """Clone a configuration repository"""
        local_path = False

        if path is not None:
            path = pathlib.Path(path)
            # Use local path when available
            assert path.is_dir(), f"Invalid repo dir {path}"
            LOG.info(f"Using local configuration in {path}")
            local_path = True
        elif url is not None:
            # Clone from remote repository
            path = pathlib.Path(tempfile.mkdtemp(suffix=url[url.rindex("/") + 1 :]))

            # Clone the configuration repository
            LOG.info(f"Cloning {url}")
            cmd = ["git", "clone", "--quiet", url, str(path)]
            subprocess.check_output(cmd)
            LOG.info(f"Using cloned config files in {path}")
        else:
            raise Exception("You need to specify a repo url or local path")

        # Update to specified revision
        # Fallback to pulling remote references
        if not local_path and revision is not None:
            LOG.info(f"Updating repo to {revision}")
            try:
                cmd = ["git", "checkout", revision, "-q"]
                subprocess.check_output(cmd, cwd=str(path))

            except subprocess.CalledProcessError:
                LOG.info("Updating failed, trying to pull")
                cmd = ["git", "pull", "origin", revision, "-q"]
                subprocess.check_output(cmd, cwd=str(path))

        return path
