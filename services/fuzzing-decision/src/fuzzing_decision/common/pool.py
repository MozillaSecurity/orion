# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import abc
import itertools
import logging
import re
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import (
    Any,
    Generator,
    Iterable,
)

import dateutil.parser
import yaml

LOG = logging.getLogger(__name__)

# fields that must exist in pool.yml (once flattened), and their types
COMMON_FIELD_TYPES = types.MappingProxyType(
    {
        "artifacts": dict,
        "cloud": str,
        "command": list,
        "container": (str, dict),
        "cpu": str,
        "cycle_time": (int, str),
        "demand": bool,
        "disk_size": (int, str),
        "env": dict,
        "imageset": str,
        "machine_types": list,
        "max_run_time": (int, str),
        "name": str,
        "nested_virtualization": bool,
        "platform": str,
        "preprocess": str,
        "run_as_admin": bool,
        "schedule_start": (datetime, str),
        "routes": list,
        "scopes": list,
        "tasks": int,
        "worker": str,
    }
)
# fields that must exist in every pool.yml
COMMON_REQUIRED_FIELDS = frozenset(("name",))
POOL_CONFIG_FIELD_TYPES = types.MappingProxyType(
    {k: v for k, v in itertools.chain(COMMON_FIELD_TYPES.items(), [("parents", list)])}
)
POOL_MAP_FIELD_TYPES = types.MappingProxyType(
    {k: v for k, v in itertools.chain(COMMON_FIELD_TYPES.items(), [("apply_to", list)])}
)
POOL_MAP_REQUIRED_FIELDS = frozenset(COMMON_REQUIRED_FIELDS | {"apply_to"})
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


def parse_size(size: str) -> float:
    """Parse a human readable size like "4g" into (4 * 1024 * 1024 * 1024)

    Args:
        size: size as a string, with si prefixes allowed

    Returns:
        size with si prefix expanded
    """
    match = re.match(r"(\d+\.\d+|\d+)([kmgt]?)b?", size, re.IGNORECASE)
    assert match is not None, "size should be a number followed by optional si prefix"
    result = float(match.group(1))
    multiplier = {
        "": 1,
        "k": 1024,
        "m": 1024 * 1024,
        "g": 1024 * 1024 * 1024,
        "t": 1024 * 1024 * 1024 * 1024,
    }[match.group(2).lower()]
    return result * multiplier


def parse_time(time: str) -> int:
    """Parse a human readable time like 1h30m or 30m10s

    Args:
        time: time as a string

    Returns:
        time in seconds
    """
    result = 0
    got_anything = False
    while time:
        match = re.match(r"(\d+)([wdhms]?)(.*)", time, re.IGNORECASE)
        assert match is not None, "time should be a number followed by optional unit"
        if match.group(2):
            multiplier = {
                "w": 7 * 24 * 60 * 60,
                "d": 24 * 60 * 60,
                "h": 60 * 60,
                "m": 60,
                "s": 1,
            }[match.group(2).lower()]
        else:
            assert not match.group(3), "trailing data"
            assert not got_anything, "multipart time must specify all units"
            multiplier = 1
        got_anything = True
        result += int(match.group(1)) * multiplier
        time = match.group(3)
    assert got_anything, "no time could be parsed"
    return result


class MachineTypes:
    """Database of all machine types available, by provider and architecture."""

    def __init__(self, machines_data: dict[str, Any]) -> None:
        for provider, provider_archs in machines_data.items():
            assert provider in PROVIDERS, f"unknown provider: {provider}"
            for arch, machines in provider_archs.items():
                assert arch in ARCHITECTURES, f"unknown architecture: {provider}.{arch}"
                for machine, spec in machines.items():
                    extra = list(set(spec) - {"zone_blacklist"})
                    assert not extra, (
                        f"machine {provider}.{arch}.{machine} has unknown keys: "
                        f"{extra!r}"
                    )
        self._data = machines_data

    @classmethod
    def from_file(cls, machines_yml: Path) -> MachineTypes:
        assert machines_yml.is_file()
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


class CommonPoolConfiguration(abc.ABC):
    """Fuzzing Pool Configuration

    Attributes:
        artifacts: dictionary of local path ->
                   {url: taskcluster path, type: file/directory}
        cloud: cloud provider, like aws or gcp
        command: list of strings, command to execute in the image/container
        container: image to run. takes the same options as
            https://docs.taskcluster.net/docs/reference/workers/docker-worker/payload
        cpu: cpu architecture (eg. x64/arm64)
        cycle_time: schedule for running this pool in seconds
        demand: whether an on-demand instance is required (vs. spot/preemptible)
        disk_size: disk size in GB
        env: dictionary of environment variables passed to the target
        imageset: imageset name in community-tc-config/config/imagesets.yml
        machine_types: machine types to use for this pool
        max_run_time: maximum run time of this pool in seconds
        name: descriptive name of the configuration
        platform: operating system of the target (linux, macos, windows)
        pool_id: basename of the pool on disk (eg. "pool1" for pool1.yml)
        preprocess: name of pool configuration to apply and run before fuzzing tasks
        run_as_admin: whether to run as Administrator or unprivileged user
                      (only valid when platform is windows)
        schedule_start: reference date for `cycle_time` scheduling
        routes: list of taskcluster notification routes to enable on the target
        scopes: list of taskcluster scopes required by the target
        tasks: number of tasks to run
        worker: TC worker type
    """

    FIELD_TYPES: types.MappingProxyType
    REQUIRED_FIELDS: frozenset

    def __init__(
        self,
        pool_id: str,
        data: dict[str, Any],
        base_dir: Path | None = None,
    ) -> None:
        LOG.debug(f"creating pool {pool_id}")
        extra = list(set(data) - set(self.FIELD_TYPES))
        missing = list(set(self.REQUIRED_FIELDS) - set(data))
        assert not missing, f"configuration is missing fields: {missing!r}"
        assert not extra, f"configuration has extra fields: {extra!r}"

        # "normal" fields
        self.pool_id = pool_id
        self.base_dir = base_dir or Path.cwd()

        # check that all fields are of the right type (or None)
        for field, cls in self.FIELD_TYPES.items():
            if data.get(field) is not None:
                if isinstance(cls, tuple):
                    expected = f"'{cls[0].__name__}' or '{cls[1].__name__}'"
                else:
                    expected = f"'{cls.__name__}'"
                assert isinstance(data[field], cls), (
                    f"expected '{field}' to be {expected}, got "
                    f"'{type(data[field]).__name__}'"
                )
        if isinstance(data.get("container"), dict):
            value = data["container"]
            assert value is not None
            assert isinstance(value, dict)
            assert "type" in value, "'container' missing required key: 'type'"
            assert value["type"] in {
                "docker-image",
                "indexed-image",
                "task-image",
            }, f"unknown 'container.type': {value['type']}"
            required_keys = {
                "docker-image": {"type", "name"},
                "indexed-image": {"type", "path", "namespace"},
                "task-image": {"type", "path", "taskId"},
            }[value["type"]]
            have_keys = set(value.keys())
            missing_keys = required_keys - have_keys
            extra_keys = have_keys - required_keys
            assert not missing_keys, (
                f"missing required keys for 'container' with type '{value['type']}': "
                f"{', '.join(missing_keys)}"
            )
            assert not extra_keys, (
                f"unknown keys for 'container' with type '{value['type']}': "
                f"{', '.join(extra_keys)}"
            )
            for k, v in value.items():
                assert isinstance(v, str), (
                    f"unexpected type for 'container.{k}': {type(v).__name__}"
                )
        for key, value in data.get("artifacts", {}).items():
            assert isinstance(key, str), (
                f"expected artifact '{key!r}' name to be 'str', "
                f"got '{type(key).__name__}'"
            )
            assert isinstance(value, dict), (
                f"expected artifact '{key}' value to be 'dict', "
                f"got '{type(value).__name__}'"
            )
            assert set(value.keys()) == {
                "url",
                "type",
            }, f"expected artifact '{key}' object to contain only keys: url, type"
            assert isinstance(value["url"], str), (
                f"expected artifact '{key}' .url to be 'str', "
                f"got '{type(value['url']).__name__}'"
            )
            assert value["type"] in {
                "file",
                "directory",
            }, f"expected artifact '{key}' .type to be one of: file, directory"
        for key, value in data.get("env", {}).items():
            assert isinstance(key, str), (
                f"expected env '{key!r}' name to be 'str', got '{type(key).__name__}'"
            )
            assert isinstance(value, (int, str)), (
                f"expected env '{key}' value to be 'int' or 'str', got "
                f"'{type(value).__name__}'"
            )

        self.container = data.get("container")
        self.demand = data.get("demand")
        self.imageset = data.get("imageset")
        self.name = data["name"]
        assert self.name is not None, "name is required for every configuration"
        self.nested_virtualization = data.get("nested_virtualization")
        self.platform = data.get("platform")
        self.tasks = data.get("tasks")
        self.preprocess = data.get("preprocess")
        self.run_as_admin = data.get("run_as_admin")

        # dict fields
        self.artifacts = data.get("artifacts", {})
        self.env = {k: str(v) for k, v in data.get("env", {}).items()}

        # list fields
        # command is an overwriting field, null is allowed
        self.command: list[str] | None
        if data.get("command") is not None:
            assert data["command"] is not None
            self.command = data["command"].copy()
        else:
            self.command = None
        self.machine_types: list[str] | None = None
        if data.get("machine_types") is not None:
            self.machine_types = data["machine_types"].copy()
        self.routes = data.get("routes", []).copy()
        self.scopes = data.get("scopes", []).copy()

        # size fields
        self.disk_size = None
        if data.get("disk_size") is not None:
            self.disk_size = int(parse_size(str(data["disk_size"])) / parse_size("1g"))

        # time fields
        self.cycle_time = None
        if data.get("cycle_time") is not None:
            self.cycle_time = parse_time(str(data["cycle_time"]))
        self.max_run_time = None
        if data.get("max_run_time") is not None:
            self.max_run_time = parse_time(str(data["max_run_time"]))
        self.schedule_start: datetime | str | None = None
        if data.get("schedule_start") is not None:
            if isinstance(data["schedule_start"], datetime):
                assert data["schedule_start"] is not None
                self.schedule_start = data["schedule_start"]
            else:
                assert data["schedule_start"] is not None
                self.schedule_start = dateutil.parser.isoparse(data["schedule_start"])

        # other special fields
        self.cpu = None
        if data.get("cpu") is not None:
            assert data["cpu"] is not None
            cpu = self.alias_cpu(data["cpu"])
            assert cpu in ARCHITECTURES
            self.cpu = cpu
        self.cloud = None
        if data.get("cloud") is not None:
            assert data["cloud"] in PROVIDERS, "Invalid cloud - use {}".format(
                ",".join(PROVIDERS)
            )
            self.cloud = data["cloud"]
        self.worker = None
        if data.get("worker") is not None:
            assert data["worker"] in WORKERS, "Invalid worker - use {}".format(
                ",".join(WORKERS)
            )
            self.worker = data["worker"]

    @classmethod
    def from_file(cls, pool_yml: Path, **kwds: Any) -> CommonPoolConfiguration:
        assert pool_yml.is_file()
        data = yaml.safe_load(pool_yml.read_text())
        return cls(
            pool_yml.stem,
            data,
            base_dir=pool_yml.parent,
            **kwds,
        )

    def get_machine_list(
        self, machine_types: MachineTypes
    ) -> Iterable[tuple[str, frozenset[str]]]:
        """
        Args:
            machine_types: database of all machine types

        Returns:
            instance type name and task capacity
        """
        assert self.cloud is not None
        assert self.cpu is not None
        assert self.machine_types
        for machine in self.machine_types:
            zone_blacklist = machine_types.zone_blacklist(self.cloud, self.cpu, machine)
            yield (machine, zone_blacklist)

    def cycle_crons(self) -> Iterable[str]:
        """Generate cron patterns that correspond to cycle_time (starting from now)

        Returns:
            One or more strings in simple cron format. If all patterns
            are installed, the result should correspond to cycle_time.
        """
        if self.schedule_start is not None:
            now = self.schedule_start
            assert isinstance(now, datetime)
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


class PoolConfiguration(CommonPoolConfiguration):
    """Fuzzing Pool Configuration

    Attributes:
        parents (list): list of parents to inherit from
    """

    FIELD_TYPES = POOL_CONFIG_FIELD_TYPES
    REQUIRED_FIELDS = COMMON_REQUIRED_FIELDS

    def __init__(
        self,
        pool_id: str,
        data: dict[str, Any],
        base_dir: Path | None = None,
        _flattened: set[str] | None = None,
    ) -> None:
        super().__init__(pool_id, data, base_dir)

        # specific fields defined in pool config
        parents_data = data.get("parents", [])
        assert parents_data is not None
        self.parents = parents_data.copy()

        top_level = False
        if _flattened is None:
            top_level = True
            _flattened = {self.pool_id}
        self._flatten(_flattened)
        if top_level:
            # set defaults
            if self.artifacts is None:
                self.artifacts = {}
            if self.command is None:
                self.command = []
            if self.env is None:
                self.env = {}
            if self.machine_types is None:
                self.machine_types = []
            if self.max_run_time is None:
                self.max_run_time = self.cycle_time
            if self.parents is None:
                self.parents = []
            if self.preprocess is None:
                self.preprocess = ""
            if self.routes is None:
                self.routes = []
            if self.scopes is None:
                self.scopes = []
            # assert complete
            missing = {
                field for field in self.FIELD_TYPES if getattr(self, field) is None
            }
            missing.discard("schedule_start")  # this field can be null
            assert not missing, f"Pool is missing fields: {list(missing)!r}"

    def create_preprocess(self) -> PoolConfiguration | None:
        """
        Return a new PoolConfiguration based on the value of self.preprocess
        """
        if not self.preprocess:
            return None
        data = yaml.safe_load((self.base_dir / f"{self.preprocess}.yml").read_text())
        pool_id = self.pool_id + "/preprocess"
        assert data["tasks"] == 1 or (self.tasks == 1 and data["tasks"] is None), (
            f"{self.preprocess} must set tasks = 1"
        )
        cannot_set = [
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
        ]
        for field in cannot_set:
            assert data.get(field) is None, f"{self.preprocess} cannot set {field}"
        data["preprocess"] = ""  # blank the preprocess field to avoid inheritance
        data["parents"] = [self.pool_id, *data.get("parents", [])]
        result = type(self)(pool_id, data, self.base_dir)
        result.name = f"{self.name} ({result.name})"
        return result

    def _flatten(self, flattened: set[str] | None) -> None:
        overwriting_fields = (
            "cloud",
            "command",
            "container",
            "cpu",
            "cycle_time",
            "demand",
            "disk_size",
            "imageset",
            "machine_types",
            "max_run_time",
            "name",
            "nested_virtualization",
            "platform",
            "preprocess",
            "schedule_start",
            "tasks",
            "run_as_admin",
            "worker",
        )
        merge_dict_fields = ("artifacts", "env")
        merge_list_fields = ("routes", "scopes")
        null_fields = {
            field for field in overwriting_fields if getattr(self, field) is None
        }
        # need to update dict values defined in self at the very end
        my_merge_dict_values = {
            field: getattr(self, field).copy() for field in merge_dict_fields
        }

        assert flattened is not None
        for parent_id in self.parents:
            assert parent_id not in flattened, (
                f"attempt to resolve cyclic configuration, {parent_id} already "
                "encountered"
            )
            flattened.add(parent_id)
            parent_obj = self.from_file(
                self.base_dir / f"{parent_id}.yml", _flattened=flattened
            )

            # "normal" overwriting fields
            for field in overwriting_fields:
                if field in null_fields:
                    if getattr(parent_obj, field) is not None:
                        LOG.debug(
                            f"overwriting field {field} in {self.pool_id} from "
                            f"{parent_id}"
                        )
                        setattr(self, field, getattr(parent_obj, field))

            # merged dict fields
            for field in merge_dict_fields:
                if getattr(parent_obj, field):
                    LOG.debug(
                        f"merging dict field {field} in {self.pool_id} from {parent_id}"
                    )
                    getattr(self, field).update(getattr(parent_obj, field))

            # merged list fields
            for field in merge_list_fields:
                if getattr(parent_obj, field):
                    LOG.debug(
                        f"merging list field {field} in {self.pool_id} from {parent_id}"
                    )
                    setattr(
                        self,
                        field,
                        list(
                            set(getattr(self, field)) | set(getattr(parent_obj, field))
                        ),
                    )

        # dict values defined in self take precedence over values defined in parents
        for field, values in my_merge_dict_values.items():
            getattr(self, field).update(values)


class PoolConfigMap(CommonPoolConfiguration):
    """A pool map is a pool config that has no `parents`, but instead has a list of
    `apply_to`.

    For each pool config in `apply_to`, the map will be applied as though it were a
    child of that config.
    """

    FIELD_TYPES = POOL_MAP_FIELD_TYPES
    REQUIRED_FIELDS = POOL_MAP_REQUIRED_FIELDS
    RESULT_TYPE = PoolConfiguration

    def __init__(
        self,
        pool_id: str,
        data: dict[str, Any],
        base_dir: Path | None = None,
    ) -> None:
        super().__init__(pool_id, data, base_dir)

        # specific fields defined in pool config
        self.apply_to = data["apply_to"].copy()

        # while these fields are not required to be defined here, they must be the same
        # for the entire set .. at least for now
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
        not_allowed = ("preprocess",)
        pools = list(self.iterpools())
        if not pools:
            return
        for field in same_fields:
            assert len({getattr(pool, field) for pool in pools}) == 1, (
                f"{field} has multiple values"
            )
            # set the field on self, so it can easily be used by decision
            setattr(self, field, getattr(pools[0], field))
        # handle machine_types separately because it is unhashable
        assert (
            len(
                {
                    frozenset(pool.machine_types)
                    if pool.machine_types is not None
                    else None
                    for pool in pools
                }
            )
            == 1
        ), "machine_types has multiple values"
        self.machine_types = pools[0].machine_types
        for field in not_allowed:
            assert not any(getattr(pool, field) for pool in pools), (
                f"{field} cannot be defined"
            )

    def apply(self, parent: str) -> CommonPoolConfiguration:
        pool_id = f"{parent}/{self.pool_id}"
        data = {k: getattr(self, k, None) for k in COMMON_FIELD_TYPES}
        # convert special fields
        if data["disk_size"] is not None:
            value = data["disk_size"]
            assert value is not None
            data["disk_size"] = value * 1024 * 1024 * 1024
        if data["schedule_start"] is not None:
            assert isinstance(data["schedule_start"], datetime)
            data["schedule_start"] = data["schedule_start"].isoformat()
        # override fields
        data["parents"] = [parent]
        data["name"] = self.RESULT_TYPE.from_file(self.base_dir / f"{parent}.yml").name
        return self.RESULT_TYPE(pool_id, data, self.base_dir)

    def iterpools(self) -> Generator[CommonPoolConfiguration, None, None]:
        for parent in self.apply_to:
            yield self.apply(parent)


class PoolConfigLoader:
    @staticmethod
    def from_file(pool_yml: Path):
        assert pool_yml.is_file()
        data = yaml.safe_load(pool_yml.read_text())
        for cls in (PoolConfiguration, PoolConfigMap):
            if (
                set(cls.FIELD_TYPES)  # type: ignore
                >= set(data.keys())
                >= cls.REQUIRED_FIELDS  # type: ignore
            ):
                return cls(pool_yml.stem, data, base_dir=pool_yml.parent)
        LOG.error(
            f"{pool_yml} has keys {data.keys()} and expected all of either "
            f"{PoolConfiguration.REQUIRED_FIELDS} or {PoolConfigMap.REQUIRED_FIELDS} "
            f"to exist."
        )
        raise RuntimeError(f"{pool_yml} type could not be identified!")
