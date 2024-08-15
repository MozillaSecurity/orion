# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.


import atexit
import logging
import pathlib
import re
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Union

import yaml
from tcadmin.appconfig import AppConfig

from ..common import taskcluster
from ..common.pool import MachineTypes
from ..common.util import onerror
from ..common.workflow import Workflow as CommonWorkflow
from . import HOOK_PREFIX, WORKER_POOL_PREFIX
from .pool import PoolConfigLoader, cancel_tasks
from .providers import AWS, GCP, Azure, Static

LOG = logging.getLogger(__name__)


class Workflow(CommonWorkflow):
    """Fuzzing decision task workflow"""

    def __init__(self) -> None:
        super().__init__()

        self.fuzzing_config_dir: Optional[pathlib.Path] = None
        self.community_config_dir: Optional[pathlib.Path] = None

        # Automatic cleanup at end of execution
        atexit.register(self.cleanup)

    def configure(self, *args: Any, **kwds: Any) -> Optional[Dict[str, object]]:
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
            local_path = pathlib.Path(local_path)

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

    def clone(self, config: Dict[str, Any]) -> None:
        """Clone remote repositories according to current setup"""
        super().clone(config)

        # Clone fuzzing & community configuration repos
        self.fuzzing_config_dir = self.git_clone(**config["fuzzing_config"])
        self.community_config_dir = self.git_clone(**config["community_config"])

    def generate(self, resources, config: Dict[str, Any]) -> None:
        # Setup resources manager to track only fuzzing instances
        for pattern in self.build_resources_patterns():
            resources.manage(pattern)

        # Load the cloud configuration from community config
        assert self.community_config_dir is not None
        clouds = {
            "aws": AWS(self.community_config_dir),
            "azure": Azure(self.community_config_dir),
            "gcp": GCP(self.community_config_dir),
            "static": Static(),
        }

        # Load the machine types
        assert self.fuzzing_config_dir is not None
        machines = MachineTypes.from_file(self.fuzzing_config_dir / "machines.yml")

        # Pass fuzzing-tc-config repository through to decision tasks, if specified
        env = {}
        if set(config["fuzzing_config"]) >= {"url", "revision"}:
            env["FUZZING_GIT_REPOSITORY"] = config["fuzzing_config"]["url"]
            env["FUZZING_GIT_REVISION"] = config["fuzzing_config"]["revision"]

        # Browse the files in the repo
        for config_file in self.fuzzing_config_dir.glob("pool*.yml"):
            pool_config = PoolConfigLoader.from_file(config_file)
            resources.update(pool_config.build_resources(clouds, machines, env))

    def build_resources_patterns(self) -> Union[List[str], str]:
        """Build regex patterns to manage our resources"""

        # Load existing workerpools from community config
        assert self.community_config_dir is not None
        path_ = self.community_config_dir / "config" / "projects" / "fuzzing.yml"
        assert path_.exists(), f"Missing fuzzing community config in {path_}"
        community = yaml.safe_load(path_.read_text())
        assert "fuzzing" in community, "Missing fuzzing main key in community config"

        def _suffix(data: Dict[str, Any], key: str) -> str:
            existing = data.get(key, {})
            if not existing:
                # Manage every resource possible
                return ".*"

            # Exclude existing resources from managed resources
            LOG.info(
                "Found existing {} in community config: {}".format(
                    key, ", ".join(existing)
                )
            )
            return "(?!({})$)".format("|".join(existing))

        hook_suffix = _suffix(community["fuzzing"], "hooks")
        pool_suffix = _suffix(community["fuzzing"], "workerPools")
        grant_roles = {
            "grants": {
                re.escape(role.split(f"{HOOK_PREFIX}/", 1)[1])
                for grant in community["fuzzing"].get("grants", [])
                for role in grant.get("to", [])
                if role.startswith(f"hook-id:{HOOK_PREFIX}/")
            }
        }
        role_suffix = _suffix(grant_roles, "grants")

        return [
            rf"Hook={HOOK_PREFIX}/{hook_suffix}",
            rf"WorkerPool={WORKER_POOL_PREFIX}/{pool_suffix}",
            rf"Role=hook-id:{HOOK_PREFIX}/{role_suffix}",
        ]

    def build_tasks(
        self,
        pool_name: str,
        task_id: str,
        config: Dict[str, Any],
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
        pool_config = PoolConfigLoader.from_file(path_)

        # cancel any previously running tasks
        if not dry_run:
            cancel_tasks(pool_config.task_id)

        tasks = pool_config.build_tasks(task_id, env)

        if not dry_run:
            # Create all the tasks on taskcluster
            queue = taskcluster.get_service("queue")
            for task_id_, task in tasks:
                LOG.info(f"Creating task {task['metadata']['name']} as {task_id_}")
                queue.createTask(task_id_, task)

    def cleanup(self) -> None:
        """Cleanup temporary folders at end of execution"""
        for folder in (self.community_config_dir, self.fuzzing_config_dir):
            if folder is None or not folder.exists():
                continue
            folder_ = str(folder)
            if folder_.startswith(tempfile.gettempdir()):
                LOG.info(f"Removing tempdir clone {folder_}")
                shutil.rmtree(folder_, onerror=onerror)
