# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import atexit
import logging
import re
import shutil
import tempfile
from itertools import chain
from pathlib import Path
from typing import Any

from tcadmin.appconfig import AppConfig

from ..common import taskcluster
from ..common.pool import FuzzingPoolConfig, MachineTypes
from ..common.util import onerror
from ..common.workflow import Workflow as CommonWorkflow
from . import WORKER_POOL_PREFIX
from .pool import WorkerPool, build_resources, build_tasks, cancel_tasks
from .providers import AWS, GCP, Azure, Provider, Static

LOG = logging.getLogger(__name__)


class Workflow(CommonWorkflow):
    """Fuzzing decision task workflow"""

    def __init__(self) -> None:
        super().__init__()

        self.fuzzing_config_dir: Path | None = None
        self.fxci_config_dir: Path | None = None

        # Automatic cleanup at end of execution
        atexit.register(self.cleanup)

    def configure(self, *args: Any, **kwds: Any) -> dict[str, object] | None:
        config = super().configure(*args, **kwds)
        if config is None:
            raise Exception("Specify local_path XOR secret")
        return config

    @classmethod
    async def tc_admin_boot(cls, resources) -> None:
        """Setup the workflow to be usable by tc-admin"""
        appconfig = AppConfig.current()

        local_path = appconfig.options.get("fuzzing_configuration")
        if local_path is not None:
            local_path = Path(local_path)

        # Configure workflow using tc-admin options
        workflow = cls()
        config = workflow.configure(
            local_path=local_path,
            secret=appconfig.options.get("fuzzing_taskcluster_secret"),
            fuzzing_git_repository=appconfig.options.get("fuzzing_git_repository"),
            fuzzing_git_revision=appconfig.options.get("fuzzing_git_revision"),
        )

        assert config is not None
        # Retrieve remote repositories
        workflow.clone(config)

        # Then generate all our Taskcluster resources
        workflow.generate(resources, config)

    def clone(self, config: dict[str, Any]) -> None:
        """Clone remote repositories according to current setup"""
        super().clone(config)

        # Clone fuzzing & FXCI configuration repos
        self.fuzzing_config_dir = self.git_clone(**config["fuzzing_config"])
        self.fxci_config_dir = self.git_clone(**config["community_config"])

    def _clouds(self) -> dict[str, Provider]:
        """Cloud providers for FXCI's supported worker pool types."""
        assert self.fxci_config_dir is not None
        base = self.fxci_config_dir
        return {
            "aws": AWS(base),
            "azure": Azure(base),
            "gcp": GCP(base),
            "static": Static(),
        }

    def generate(self, resources, config: dict[str, Any]) -> None:
        clouds = self._clouds()

        # Load the machine types
        assert self.fuzzing_config_dir is not None
        machines = MachineTypes.from_file(self.fuzzing_config_dir / "machines.yml")

        # Pass fuzzing-tc-config repository through to decision tasks, if specified
        env = {}
        if set(config["fuzzing_config"]) >= {"url", "revision"}:
            env["FUZZING_GIT_REPOSITORY"] = config["fuzzing_config"]["url"]
            env["FUZZING_GIT_REVISION"] = config["fuzzing_config"]["revision"]

        generated: list[Any] = []
        retired_worker_pool_ids: set[str] = set()
        for config_file in self.fuzzing_config_dir.glob("pool*.yml"):
            pool_configs = list(FuzzingPoolConfig.from_file(config_file))
            if not pool_configs:
                # an apply_to group whose pools are all disabled
                continue
            if pool_configs[0].cloud == "static":
                # build_resources() represents an apply_to group with one pool,
                # keyed by the first entry's hook ID.
                retired_worker_pool_ids.add(
                    f"{WORKER_POOL_PREFIX}/{pool_configs[0].hook_id}"
                )
            generated.extend(build_resources(pool_configs, clouds, machines, env))

        extra_pools_path = self.fuzzing_config_dir / "workers.yml"
        if extra_pools_path.is_file():
            worker_pools = list(WorkerPool.from_file_iter(extra_pools_path))
            retired_worker_pool_ids.update(
                f"{WORKER_POOL_PREFIX}/{pool.name}"
                for pool in worker_pools
                if pool.cloud == "static"
            )
            for pool in worker_pools:
                generated.extend(pool.build_resources(clouds, machines))

        # fxci-config manages its own infrastructure resources. Manage only the
        # exact IDs generated here, plus prior worker-pool IDs whose configured
        # static replacements no longer need Taskcluster-managed capacity. tc-admin
        # dispatches current-resource fetches from the leading kind=, and MatchList
        # already roots regex matching at the start of each ID.
        for resource in generated:
            resources.manage(f"{re.escape(resource.id)}$")

        for worker_pool_id in retired_worker_pool_ids:
            resources.manage(f"{re.escape(f'WorkerPool={worker_pool_id}')}$")

        resources.update(generated)
        # Pools removed from configuration are still cleaned up manually.

    def build_tasks(
        self,
        pool_name: str,
        task_id: str,
        config: dict[str, Any],
        dry_run: bool = False,
    ) -> None:
        assert self.fuzzing_config_dir is not None
        path_ = self.fuzzing_config_dir / f"{pool_name}.yml"
        assert path_.exists(), f"Missing pool {pool_name}"

        # Pass fuzzing-tc-config repository through to tasks, if specified
        env = {}
        if set(config["fuzzing_config"]) >= {"url", "revision"}:
            env["FUZZING_GIT_REPOSITORY"] = config["fuzzing_config"]["url"]
            env["FUZZING_GIT_REVISION"] = config["fuzzing_config"]["revision"]

        # Build tasks needed for a specific pool
        pool_configs = list(FuzzingPoolConfig.from_file(path_))

        # cancel any previously running tasks
        if not dry_run:
            cancel_tasks(pool_configs[0].hook_id)

        tasks = chain.from_iterable(build_tasks(p, task_id, env) for p in pool_configs)

        if not dry_run:
            # Create all the tasks on taskcluster
            queue = taskcluster.get_service("queue")
            for task_id_, task in tasks:
                LOG.info(f"Creating task {task['metadata']['name']} as {task_id_}")
                queue.createTask(task_id_, task)

    def cleanup(self) -> None:
        """Cleanup temporary folders at end of execution"""
        for folder in (self.fxci_config_dir, self.fuzzing_config_dir):
            if folder is None or not folder.exists():
                continue
            folder_ = str(folder)
            if folder_.startswith(tempfile.gettempdir()):
                LOG.info(f"Removing tempdir clone {folder_}")
                shutil.rmtree(folder_, onerror=onerror)
