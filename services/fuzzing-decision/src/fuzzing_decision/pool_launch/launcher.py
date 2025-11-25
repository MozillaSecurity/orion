# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import os
import sys
from ctypes import get_errno
from logging import getLogger
from pathlib import Path
from platform import system
from shutil import which
from subprocess import call
from typing import Any

from ..common.pool import FuzzingPoolConfig
from ..common.workflow import Workflow

LOG = getLogger(__name__)


class PoolLauncher(Workflow):
    """Launcher for a fuzzing pool, using docker parameters from a private repo."""

    def __init__(
        self, command: list[str], pool_name: str | None, preprocess: bool = False
    ) -> None:
        super().__init__()

        self.apply: str | None
        self.command = command.copy()
        self.environment = os.environ.copy()
        self.pool_name: str | None
        if pool_name is not None and "/" in pool_name:
            self.apply, self.pool_name = pool_name.split("/")
        else:
            self.pool_name = pool_name
            self.apply = None
        self.preprocess = preprocess
        self.log_dir = Path("/logs" if sys.platform == "linux" else "logs")

    def clone(self, config: dict[str, Any]) -> None:
        """Clone remote repositories according to current setup"""
        super().clone(config)

        # Clone fuzzing & community configuration repos
        self.fuzzing_config_dir = self.git_clone(**config["fuzzing_config"])

    def load_params(self) -> None:
        assert self.pool_name is not None
        if self.apply is not None:
            path = self.fuzzing_config_dir / f"{self.apply}.yml"
        else:
            path = self.fuzzing_config_dir / f"{self.pool_name}.yml"
        assert path.exists(), f"Missing pool {path.stem}"

        # Build tasks needed for a specific pool
        pool_configs = FuzzingPoolConfig.from_file(path)
        if self.apply is not None:
            pool_id = f"{self.pool_name}/{self.apply}"
            for pool_config in pool_configs:
                if pool_config.pool_id == pool_id:
                    break
            else:
                raise Exception(f"Failed to find {pool_id}")
        else:
            pool_config = next(pool_configs)
            if self.preprocess:
                pool_config = next(pool_config.get_preprocess())

        if pool_config.command:
            assert not self.command, "Specify command-line args XOR pool.command"
            self.command = pool_config.command.copy()
        for key, value in pool_config.env.items():
            # don't override existing env vars
            if key in self.environment:
                LOG.info("Skip setting existing environment variable '%s'", key)
                continue
            self.environment[key] = value
        self.environment["FUZZING_POOL_NAME"] = pool_config.name

    def docker_cmd(self, image: str, expand: bool = False) -> list[str]:
        cmd = [
            "docker",
            "run",
            "--rm",
            "-it",
            "-e",
            "TASKCLUSTER_ROOT_URL",
            "-e",
            "TASKCLUSTER_ACCESS_TOKEN",
            "-e",
            "TASKCLUSTER_CLIENT_ID",
        ]

        for key, env in self.environment.items():
            if os.environ.get(key) != env:
                if expand:
                    cmd.extend(("-e", f"{key}={env}"))
                else:
                    cmd.extend(("-e", f"{key}"))

        cmd.append(image)
        cmd.extend(self.command)
        return cmd

    def exec(self, in_docker: str | None = None) -> None:
        assert self.command

        if system() == "Windows" and not Path(self.command[0]).is_file():
            binary = which(self.command[0])
            assert binary is not None, "Couldn't resolve script executable"
            self.command[0] = binary

        if in_docker is not None:
            self.command = self.docker_cmd(in_docker)

        if self.in_taskcluster:
            LOG.info(f"Creating private logs directory '{self.log_dir}/'")
            if self.log_dir.is_dir():
                self.log_dir.chmod(0o777)
            else:
                self.log_dir.mkdir(mode=0o777)

            LOG.info(f"Redirecting stdout/stderr to {self.log_dir}/live.log")
            sys.stdout.flush()
            sys.stderr.flush()

            # redirect stdout/stderr to a log file
            # not sure if the assertions would print
            with (self.log_dir / "live.log").open("w") as log:
                if system() == "Windows":
                    sys.exit(
                        call(self.command, env=self.environment, stdout=log, stderr=log)
                    )

                result = os.dup2(log.fileno(), 1)
                assert result != -1, "dup2 failed: " + os.strerror(get_errno())
                result = os.dup2(log.fileno(), 2)
                assert result != -1, "dup2 failed: " + os.strerror(get_errno())
        else:
            sys.stdout.flush()
            sys.stderr.flush()

        if system() == "Windows":
            sys.exit(call(self.command, env=self.environment))

        os.execvpe(self.command[0], self.command, self.environment)
