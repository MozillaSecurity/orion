# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.


import logging
import os
import pathlib
import subprocess
import tempfile
from typing import Any, Dict, Optional

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
        local_path: Optional[pathlib.Path] = None,
        secret: Optional[str] = None,
        fuzzing_git_repository: Optional[str] = None,
        fuzzing_git_revision: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
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

    def clone(self, config: Dict[str, str]) -> None:
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

    def git_clone(
        self,
        url: Optional[str] = None,
        path: Optional[pathlib.Path] = None,
        revision: Optional[str] = None,
        **kwargs: Any,
    ) -> pathlib.Path:
        """Clone a configuration repository"""

        if path is not None:
            path = pathlib.Path(path)
            # Use local path when available
            assert path.is_dir(), f"Invalid repo dir {path}"
            LOG.info(f"Using local configuration in {path}")
        elif url is not None:
            # Clone from remote repository
            path = pathlib.Path(tempfile.mkdtemp(suffix=url[url.rindex("/") + 1 :]))

            # Clone the configuration repository
            if revision is None:
                revision = "master"
            LOG.info(f"Cloning {url} @ {revision}")
            cmd = ["git", "init", str(path)]
            subprocess.check_output(cmd)
            cmd = ["git", "remote", "add", "origin", url]
            subprocess.check_output(cmd, cwd=str(path))
            cmd = ["git", "fetch", "-q", "origin", revision]
            subprocess.check_output(cmd, cwd=str(path))
            cmd = ["git", "-c", "advice.detachedHead=false", "checkout", revision]
            subprocess.check_output(cmd, cwd=str(path))
            LOG.info(f"Using cloned config files in {path}")
        else:
            raise Exception("You need to specify a repo url or local path")

        return path
