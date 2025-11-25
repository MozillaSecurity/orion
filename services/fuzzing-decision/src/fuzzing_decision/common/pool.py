# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import logging
import types
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import (
    Any,
    Iterable,
    Iterator,
)

import dateutil.parser
import yaml

from .util import parse_size, parse_time, validate_schema_by_name

LOG = logging.getLogger(__name__)

CPU_ALIASES = types.MappingProxyType(
    {
        "x86_64": "x64",
        "amd64": "x64",
        "x86-64": "x64",
        "x64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
)
PROVIDERS = frozenset(("aws", "azure", "gcp", "static"))
ARCHITECTURES = frozenset(("x64", "arm64"))
WORKERS = frozenset(("generic", "docker", "d2g"))


class ConfigurationError(Exception):
    """Error in pool configuration"""


class MachineTypes:
    """Database of all machine types available, by provider and architecture."""

    def __init__(self, machines_data: dict[str, Any]) -> None:
        validate_schema_by_name(instance=machines_data, name="Machines")
        self._data = machines_data

    @classmethod
    def from_file(cls, machines_yml: Path) -> MachineTypes:
        return cls(yaml.safe_load(machines_yml.read_text()))

    def cpus(self, provider: str, architecture: str, machine: str):
        return self._data[provider][architecture][machine]["cpu"]

    def zone_blacklist(
        self,
        provider: str,
        architecture: str,
        machine: str,
    ) -> frozenset[str]:
        machine_data = (
            self._data.get(provider, {}).get(architecture, {}).get(machine, {})
        )
        return frozenset(machine_data.get("zone_blacklist", []))


@dataclass
class FuzzingPoolConfig:
    # An array of configurations to apply this configuration to
    apply_to: list[str]
    # Object containing artifact mappings for the task instance
    # { container_path: { type: (file|directory), url: where to map artifact in TC } }
    artifacts: dict[str, dict[str, str]]
    base_dir: Path
    # The cloud service where the task should run
    cloud: str
    # List of commands to run
    command: list[str]
    # Docker image (might be tag or taskcluster specification object)
    container: str | dict[str, str]
    # CPU architecture type
    cpu: str
    # Maximum time before completely refreshing this pool
    cycle_time: int
    # Boolean indicating if task requires an on-demand instance
    demand: bool
    disk_size: int
    # Environment variables to be set in the task
    env: dict
    # The name of the taskcluster imageset
    imageset: str
    # An array of machine types to use for a given task
    machine_types: list
    # Maximum time to run each instance
    max_run_time: int
    # Human description
    name: str
    # Task requires an instance type that supported nested virtualization
    nested_virtualization: bool
    # An array of configurations to inherit from
    parents: list[str]
    # Platform (OS)
    platform: str
    # Pool ID (eg. pool100)
    pool_id: str
    # A configuration item to run as part of the preprocess stage
    preprocess: str
    # Boolean indicating if the image should be run with administrator privileges
    run_as_admin: bool
    # Date and time to start applying this configuration
    schedule_start: datetime | None
    # An array of routes to apply to the task
    routes: list
    # An array of taskcluster scopes to apply to the task
    scopes: list
    # Number of tasks to run
    tasks: int
    # Taskcluster worker type
    worker: str

    @classmethod
    def _load_partial(cls, path: Path, loaded: set[str]) -> dict[str, Any]:
        name = path.stem
        if name in loaded:
            raise ConfigurationError(
                f"attempt to resolve cyclic configuration, {name} already encountered"
            )
        raw = yaml.safe_load(path.read_text())
        result: dict[str, Any] = {}

        for parent in raw.get("parents", []):
            par = cls._load_partial(path.parent / f"{parent}.yml", loaded)
            cls._overwrite(result, par)
        cls._overwrite(result, raw)
        return result

    @classmethod
    def _fixup_fields(cls, raw: dict[str, Any], path: Path) -> None:
        if isinstance(raw.get("schedule_start"), datetime):
            raw["schedule_start"] = raw["schedule_start"].isoformat()

        validate_schema_by_name(instance=raw, name="Pool")

        # size fields
        raw["disk_size"] = int(parse_size(str(raw["disk_size"])) / parse_size("1g"))

        # time fields
        raw["cycle_time"] = parse_time(str(raw["cycle_time"]))
        raw["max_run_time"] = parse_time(str(raw["max_run_time"]))
        if raw.get("schedule_start"):
            raw["schedule_start"] = dateutil.parser.isoparse(raw["schedule_start"])
        else:
            raw["schedule_start"] = None

        # other special fields
        raw["cpu"] = cls.alias_cpu(raw["cpu"])
        raw.setdefault("apply_to", [])
        raw.setdefault("artifacts", {})
        raw.setdefault("command", [])
        raw.setdefault("preprocess", "")
        raw.setdefault("routes", [])
        raw["env"] = {k: str(v) for k, v in raw["env"].items()}
        raw["base_dir"] = path.parent
        raw["pool_id"] = path.stem

    @staticmethod
    def _overwrite(result: dict[str, Any], overlay: dict[str, Any]):
        # null -> no-op
        overlay = {k: v for k, v in overlay.items() if v is not None}
        # some dicts should be merged
        for k in ("artifacts", "env"):
            if k in overlay:
                result.setdefault(k, {})
                result[k].update(overlay.pop(k))
        # some lists should be merged
        for k in ("routes", "scopes"):
            if k in overlay:
                result.setdefault(k, [])
                result[k].extend(overlay.pop(k))
        # merge the rest
        result.update(overlay)

    @classmethod
    def from_file(cls, path: Path) -> Iterator[FuzzingPoolConfig]:
        apply_pool = path.stem
        raw = cls._load_partial(path, set())

        if not raw.get("apply_to"):
            cls._fixup_fields(raw, path)
            yield cls(**raw)
            return

        # must be the same for the entire set .. at least for now
        same_fields = (
            "cloud",
            "cpu",
            "cycle_time",
            "demand",
            "disk_size",
            "imageset",
            "nested_virtualization",
            "platform",
            "schedule_start",
            "worker",
        )
        same_values = None

        for pool in raw["apply_to"]:
            new = cls._load_partial(path.parent / f"{pool}.yml", set())

            # skip disabled pools
            if not new["tasks"]:
                continue

            cls._overwrite(new, raw)
            cls._fixup_fields(new, path)
            new["pool_id"] = f"{pool}/{path.stem}"

            # check for field violations
            my_same_values = {field: new[field] for field in same_fields}
            if same_values is None:
                same_values = my_same_values
            else:
                # Pools with "apply_to" set require certain values to be the same
                # across all tasks in the group.
                if same_values != my_same_values:
                    diffs = {
                        field
                        for field in same_fields
                        if my_same_values[field] != same_values[field]
                    }
                    raise ConfigurationError(
                        f"Pool {pool}/{apply_pool} has different values than others in "
                        f"{apply_pool} for fields: {','.join(diffs)}"
                    )
            if new["preprocess"]:
                raise ConfigurationError(
                    f"Pool {pool}/{apply_pool} sets preprocess, "
                    "not allowed with apply_to"
                )

            yield cls(**new)

    @property
    def task_id(self) -> str:
        return f"{self.platform}-{self.pool_id}"

    # for scope calculations, the real worker pool name must be used
    @property
    def config_pool_id(self) -> str:
        if "/" in self.pool_id:
            _apply, pool_id = self.pool_id.split("/", 1)
            return pool_id
        return self.pool_id

    @property
    def hook_id(self) -> str:
        return f"{self.platform}-{self.config_pool_id}"

    def get_preprocess(self) -> Iterator[FuzzingPoolConfig]:
        if self.preprocess:
            pool_id = f"{self.pool_id}/preprocess"
            this_path = self.base_dir / f"{self.pool_id}.yml"
            preproc_path = self.base_dir / f"{self.preprocess}.yml"
            this = self._load_partial(this_path, set())
            preproc = self._load_partial(preproc_path, set())
            name = f"{self.name} ({preproc['name']})"
            self._overwrite(this, preproc)
            this["name"] = name
            self._fixup_fields(this, this_path)
            this["pool_id"] = pool_id
            if this["tasks"] != 1:
                raise ConfigurationError(f"Pool {pool_id} must set tasks = 1")
            cannot_set = (
                "disk_size",
                "cpu",
                "cloud",
                "cycle_time",
                "demand",
                "imageset",
                "machine_types",
                "nested_virtualization",
                "platform",
                "preprocess",
                "schedule_start",
            )
            for field in cannot_set:
                if this[field] != getattr(self, field):
                    raise ConfigurationError(
                        f"Pool {pool_id} cannot change field {field}"
                    )
            yield type(self)(**this)

    def get_machine_list(
        self, machine_types: MachineTypes
    ) -> Iterable[tuple[str, frozenset[str]]]:
        """
        Args:
            machine_types: database of all machine types

        Returns:
            instance type name and task capacity
        """
        for machine in self.machine_types:
            zone_blacklist = machine_types.zone_blacklist(self.cloud, self.cpu, machine)
            yield (machine, zone_blacklist)

    def cycle_crons(self) -> Iterable[str]:
        """Generate cron patterns that correspond to cycle_time (starting from now)

        Returns:
            One or more strings in simple cron format. If all patterns
            are installed, the result should correspond to cycle_time.
        """
        # if pool is disabled, this hook should never fire
        if not self.tasks:
            return

        if self.schedule_start is not None:
            now = self.schedule_start
            if now.utcoffset() is None:
                # no timezone was specified. treat it as UTC
                now = now.replace(tzinfo=timezone.utc)
            else:
                # timezone was given, shift the datetime to be equivalent but in UTC
                now = now.astimezone(timezone.utc)
        else:
            now = datetime.now(timezone.utc)
        assert self.cycle_time
        interval = timedelta(seconds=self.cycle_time)

        # special case if the cycle time is a factor of 24 hours
        if (24 * 60 * 60) % self.cycle_time == 0:
            stop = now + timedelta(days=1)
            while now < stop:
                now += interval
                yield f"{now.second} {now.minute} {now.hour} * * *"
            return

        # special case if the cycle time is a factor of 7 days
        if (7 * 24 * 60 * 60) % self.cycle_time == 0:
            stop = now + timedelta(days=7)
            while now < stop:
                now += interval
                weekday = now.isoweekday() % 7
                yield f"{now.second} {now.minute} {now.hour} * * {weekday}"
            return

        # if the cycle can't be represented as a daily or weekly pattern, then it is
        #   awkward to represent in cron format: resort to generating an annual schedule
        # the cycle will glitch if it really runs for the full year, and either have
        #   dead time or overlapping runs, happening once around the anniversary.
        stop = now + timedelta(days=365)
        while now < stop:
            now += interval
            yield f"{now.second} {now.minute} {now.hour} {now.day} {now.month} *"

    @staticmethod
    def alias_cpu(cpu_name: str) -> str:
        """
        Args:
            cpu_name: a cpu string like x86_64 or x64

        Returns:
            x64 or arm64
        """
        return CPU_ALIASES[cpu_name.lower()]
