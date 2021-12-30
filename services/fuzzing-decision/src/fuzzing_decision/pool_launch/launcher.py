# -*- coding: utf-8 -*-

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

from ..common.pool import PoolConfigLoader
from ..common.workflow import Workflow

LOG = getLogger(__name__)


class PoolLauncher(Workflow):
    """Launcher for a fuzzing pool, using docker parameters from a private repo."""

    def __init__(self, command, pool_name, preprocess=False):
        super().__init__()

        self.command = command.copy()
        self.environment = os.environ.copy()
        if pool_name is not None and "/" in pool_name:
            self.apply, self.pool_name = pool_name.split("/")
        else:
            self.pool_name = pool_name
            self.apply = None
        self.preprocess = preprocess
        self.log_dir = Path("/logs" if sys.platform == "linux" else "logs")

    def clone(self, config):
        """Clone remote repositories according to current setup"""
        super().clone(config)

        # Clone fuzzing & community configuration repos
        self.fuzzing_config_dir = self.git_clone(**config["fuzzing_config"])

    def load_params(self):
        path = self.fuzzing_config_dir / f"{self.pool_name}.yml"
        assert path.exists(), f"Missing pool {self.pool_name}"

        # Build tasks needed for a specific pool
        pool_config = PoolConfigLoader.from_file(path)
        if self.preprocess:
            pool_config = pool_config.create_preprocess()
            assert pool_config is not None, "preprocess given, but could not be loaded"
        if self.apply is not None:
            pool_config = pool_config.apply(self.apply)

        if pool_config.command:
            assert not self.command, "Specify command-line args XOR pool.command"
            self.command = pool_config.command.copy()
        self.environment.update(pool_config.macros)

    def exec(self):
        assert self.command

        if system() == "Windows" and not Path(self.command[0]).is_file():
            binary = which(self.command[0])
            assert binary is not None, "Couldn't resolve script executable"
            self.command[0] = binary

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
