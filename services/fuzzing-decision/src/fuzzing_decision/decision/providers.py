from __future__ import annotations

import copy
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from ..common.util import parse_time
from . import PROVIDER_IDS

LOG = logging.getLogger(__name__)


def _gcp_instance_is_invalid(
    invalid_instances: list[dict[str, Any]], zone: str, machine_type: str
) -> bool:
    """Match FXCI GCP restrictions by zone, family, profile, and suffix.

    Zone and family always constrain a rule. Missing or empty profile/suffix
    lists are wildcards, matching FXCI's `invalid-instances` configuration.
    Machine names use `<family>-<profile>[-<cpus>[-<suffix>]]`.
    """
    family = machine_type.split("-", 1)[0]
    applicable = [
        entry
        for entry in invalid_instances
        if zone in entry["zones"] and family in entry["families"]
    ]
    # Machine names outside a rule's zone/family do not need to be parsed.
    if not applicable:
        return False

    parts = machine_type.split("-")
    if len(parts) < 2:
        return False
    profile = parts[1]
    suffix = "-".join(parts[3:]) if len(parts) > 3 else None
    return any(
        (not entry.get("profiles") or profile in entry["profiles"])
        and (not entry.get("suffixes") or suffix in entry["suffixes"])
        for entry in applicable
    )


class Provider(ABC):
    @abstractmethod
    def build_launch_configs(
        self,
        imageset: str,
        machines: Iterable[tuple[str, frozenset[str]]],
        disk_size: int,
        platform: str,
        demand: bool,
        nested_virtualization: bool,
        performance_monitoring_unit: bool,
        max_tasks: int,
        worker_type: str,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError()

    def get_worker_config(
        self,
        worker: str,
        platform: str,
        max_tasks: int,
        worker_type: str,
        wst_audience: str,
        wst_server_url: str,
    ) -> dict[str, Any]:
        worker_impl = "docker-worker" if worker_type == "docker" else "generic-worker"
        out = copy.deepcopy(self._base_worker_config(worker))
        if worker_impl == "docker-worker":
            out.setdefault("dockerConfig", {})
            out.update(
                {
                    "shutdown": {
                        "enabled": True,
                        "afterIdleSeconds": parse_time("3m"),
                    }
                }
            )
            out["dockerConfig"].update(
                {"allowPrivileged": True, "allowDisableSeccomp": True}
            )

            # Clear any generic-worker specific config
            out.pop("genericWorker", None)

        else:
            out.setdefault("genericWorker", {})
            out["genericWorker"].setdefault("config", {})

            # Prevent generic worker from aborting the tasks
            out["genericWorker"]["config"].setdefault("disableOOMProtection", True)

            # Increase max runtime to 3 days
            out["genericWorker"]["config"]["maxTaskRunTime"] = parse_time("3d")

            # Allow machines to idle for some time to prevent churn
            out["genericWorker"]["config"]["idleTimeoutSecs"] = parse_time("15m")

            # Maximum number of tasks before restart
            out["genericWorker"]["config"]["numberOfTasksToRun"] = max_tasks

            out["genericWorker"]["config"].update(
                {
                    "wstAudience": wst_audience,
                    "wstServerURL": wst_server_url,
                }
            )
            if worker_type == "d2g":
                out["genericWorker"]["config"].setdefault("d2gConfig", {})
                out["genericWorker"]["config"]["d2gConfig"]["enableD2G"] = True

            # Clear any Docker specific config
            out.pop("dockerConfig", None)
            out.pop("shutdown", None)

        return out

    def _base_worker_config(self, imageset: str) -> dict[str, Any]:
        """Return provider-specific worker defaults for one image set."""
        return {}


class _UnsupportedCloud(Provider):
    """Cloud provider not yet supported by fuzzing on FXCI."""

    cloud = ""

    def __init__(self, base_dir: Path) -> None:
        del base_dir

    def build_launch_configs(
        self,
        imageset: str,
        machines: Iterable[tuple[str, frozenset[str]]],
        disk_size: int,
        platform: str,
        demand: bool,
        nested_virtualization: bool,
        performance_monitoring_unit: bool,
        max_tasks: int,
        worker_type: str,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError(
            f"{self.cloud} worker pools are not supported on FXCI"
        )


class AWS(_UnsupportedCloud):
    cloud = "AWS"


class Azure(Provider):
    """Azure2 worker-manager launch configs backed by FXCI configuration."""

    cloud = "Azure"

    @staticmethod
    def _pool_locations(pool: dict[str, Any]) -> set[str]:
        """Resolve configured locations across the variants of an Azure pool."""
        config = pool.get("config", {})
        locations = config.get("locations", [])
        variants = pool.get("variants", [{}])
        if variants is None:
            variants = [{}]
        attributes = pool.get("attributes", {})

        def resolve(value: Any, variant: dict[str, Any]) -> set[str]:
            if isinstance(value, list):
                return {item for item in value if isinstance(item, str)}
            if not isinstance(value, dict):
                return set()

            # FXCI keyed-by values resolve against pool variant attributes. Walk
            # nested keyed-by structures as well, such as by-pool-group/by-suffix.
            keyed_keys = [key for key in value if key.startswith("by-")]
            if len(keyed_keys) > 1:
                raise ValueError(f"Ambiguous Azure locations keyed-by mapping: {value}")
            keyed_by = keyed_keys[0] if keyed_keys else None
            if keyed_by is not None:
                attribute = keyed_by[3:]
                choices = value[keyed_by]
                if not isinstance(choices, dict):
                    raise ValueError(
                        f"Azure locations {keyed_by} mapping must be a mapping"
                    )
                variant_value = variant.get(attribute)
                selected = None
                if variant_value is not None:
                    exact = choices.get(str(variant_value))
                    if exact is not None:
                        selected = exact
                    else:
                        try:
                            matching = [
                                (selector, branch)
                                for selector, branch in choices.items()
                                if selector != "default"
                                and re.fullmatch(selector, str(variant_value))
                            ]
                        except re.error as exc:
                            raise ValueError(
                                f"Invalid Azure locations selector in {keyed_by}: {exc}"
                            ) from exc
                        if len(matching) > 1:
                            raise ValueError(
                                f"Ambiguous Azure locations selectors for "
                                f"{keyed_by}={variant_value!r}: "
                                f"{[selector for selector, _ in matching]}"
                            )
                        if matching:
                            selected = matching[0][1]
                if selected is None:
                    selected = choices.get("default")
                if selected is None:
                    raise ValueError(
                        f"No Azure locations branch for {keyed_by}={variant_value!r} "
                        "and no default branch"
                    )
                return resolve(selected, variant)

            raise ValueError(f"Unsupported Azure locations mapping: {value}")

        return set().union(
            *(
                resolve(
                    locations,
                    {**attributes, "environment": "firefoxci", **variant},
                )
                for variant in variants
            )
        )

    def __init__(self, base_dir: Path) -> None:
        self.images = yaml.safe_load((base_dir / "worker-images.yml").read_text())
        pools = yaml.safe_load((base_dir / "worker-pools.yml").read_text())
        azure_locations: set[str] = set()
        for pool in pools.get("pools", []):
            if pool.get("provider_id") != "azure2":
                continue
            config = pool.get("config", {})
            purpose = config.get("worker-purpose")
            if purpose is None:
                purpose = (
                    "proj-fuzzing"
                    if pool.get("pool_id", "").startswith("proj-fuzzing/")
                    else None
                )
            if purpose != "proj-fuzzing":
                continue
            azure_locations.update(self._pool_locations(pool))
        # Only project-fuzzing Azure2 pools provision the VNets/subnets used here.
        self.locations = sorted(azure_locations)
        env = yaml.safe_load((base_dir / "environments.yml").read_text())
        self.config = env["firefoxci"]["azure_config"]
        self.allowed_locations = set(self.config["location"])
        LOG.info("Loaded FXCI Azure configuration")

    def _image(self, imageset: str) -> dict[str, Any]:
        assert imageset in self.images, f"Missing image {imageset}"
        provider = PROVIDER_IDS["azure"]
        assert provider in self.images[imageset], f"No {provider} image for {imageset}"
        return self.images[imageset]

    def _image_id(self, image: dict[str, Any], location: str, subscription: str) -> str:
        azure_image = image[PROVIDER_IDS["azure"]]
        resource_group = azure_image["resource_group"]
        subscription_path = f"/subscriptions/{subscription}"
        if azure_image.get("version") == "NA":
            assert location in azure_image, f"No Azure image for {image} in {location}"
            return (
                f"{subscription_path}/resourceGroups/{resource_group}/providers/"
                f"Microsoft.Compute/images/{azure_image[location]}"
            )

        name = azure_image["name"]
        version = azure_image["version"]
        return (
            f"{subscription_path}/resourceGroups/{resource_group}/providers/"
            f"Microsoft.Compute/galleries/{name}/images/{name}/versions/{version}"
        )

    def build_launch_configs(
        self,
        imageset: str,
        machines: Iterable[tuple[str, frozenset[str]]],
        disk_size: int,
        platform: str,
        demand: bool,
        nested_virtualization: bool,
        performance_monitoring_unit: bool,
        max_tasks: int,
        worker_type: str,
    ) -> list[dict[str, Any]]:
        if nested_virtualization or performance_monitoring_unit:
            unsupported = (
                "nested virtualization"
                if nested_virtualization
                else "performance monitoring unit"
            )
            raise NotImplementedError(
                f"Azure worker pools do not support {unsupported}"
            )

        image = self._image(imageset)
        azure_image = image[PROVIDER_IDS["azure"]]
        subscription = self.config["untrusted_subscription"]
        worker_config = self.get_worker_config(
            imageset,
            platform,
            max_tasks,
            worker_type,
            self.config["wst_audience"],
            self.config["wst_server_url"],
        )
        generic_worker = worker_config.get("genericWorker", {}).get("config")
        if generic_worker is not None:
            if platform == "windows":
                generic_worker.setdefault(
                    "livelogExecutable", r"C:\generic-worker\livelog.exe"
                )
                generic_worker.setdefault(
                    "ed25519SigningKeyLocation",
                    r"C:\generic-worker\generic-worker-ed25519-signing-key.key",
                )
                generic_worker.setdefault("shutdownMachineOnIdle", True)
                generic_worker.setdefault("shutdownMachineOnInternalError", True)
                generic_worker.setdefault(
                    "taskclusterProxyExecutable",
                    r"C:\generic-worker\taskcluster-proxy.exe",
                )
        metadata = image.get("worker-type-metadata")
        if metadata and generic_worker is not None:
            generic_worker.setdefault("workerTypeMetadata", metadata)

        if azure_image.get("version") == "NA":
            image_locations = [
                location for location in self.locations if location in azure_image
            ]
        else:
            image_locations = list(self.locations)

        result = []
        for machine, region_blacklist in machines:
            for location in image_locations:
                azure_location = location.replace("-", "")
                if azure_location not in self.allowed_locations:
                    continue
                if location in region_blacklist or azure_location in region_blacklist:
                    continue

                resource_suffix = f"{location}-proj-fuzzing"
                subnet_id = (
                    f"/subscriptions/{subscription}/resourceGroups/rg-{resource_suffix}/"
                    f"providers/Microsoft.Network/virtualNetworks/vn-{resource_suffix}/"
                    f"subnets/sn-{resource_suffix}"
                )
                launch_config: dict[str, Any] = {
                    "location": azure_location,
                    "subnetId": subnet_id,
                    "hardwareProfile": {"vmSize": machine},
                    "storageProfile": {
                        "osDisk": {
                            "createOption": "FromImage",
                            "diskSizeGB": disk_size,
                        },
                        "imageReference": {
                            "id": self._image_id(image, location, subscription)
                        },
                    },
                    "workerConfig": worker_config,
                    "workerManager": {"capacityPerInstance": 1},
                }
                if platform == "windows":
                    launch_config["osProfile"] = {
                        "windowsConfiguration": {
                            "timeZone": "UTC",
                            "enableAutomaticUpdates": False,
                        }
                    }
                if azure_image.get("version") != "NA":
                    launch_config["tags"] = {
                        "deploymentId": azure_image["deployment_id"]
                    }
                if not demand:
                    launch_config.update(
                        {
                            "priority": "spot",
                            "billingProfile": {"maxPrice": -1},
                            "evictionPolicy": "Delete",
                        }
                    )
                result.append(launch_config)
        return result


class GCP(Provider):
    """Google Cloud provider config for Taskcluster"""

    def __init__(self, base_dir: Path) -> None:
        self.images = yaml.safe_load((base_dir / "worker-images.yml").read_text())
        pools = yaml.safe_load((base_dir / "worker-pools.yml").read_text())
        self._worker_defaults = pools["worker-defaults"]["worker-config"][
            "by-implementation"
        ]["generic-worker/linux-tceng"]
        env = yaml.safe_load((base_dir / "environments.yml").read_text())
        self.config = env["firefoxci"]["google_config"]
        self.regions = self.config["zones"]["by-region"]
        self.invalid_instances = self.config.get("invalid-instances", [])
        LOG.info("Loaded FXCI GCP configuration")

    def _base_worker_config(self, imageset: str) -> dict[str, Any]:
        """Copy FXCI generic-worker defaults and image metadata for this pool."""
        config = copy.deepcopy(self._worker_defaults)
        metadata = self.images[imageset].get("worker-type-metadata")
        if metadata:
            generic_worker = config.setdefault("genericWorker", {}).setdefault(
                "config", {}
            )
            generic_worker["workerTypeMetadata"] = copy.deepcopy(metadata)
        return config

    def _gcp_source_image(self, imageset: str) -> str:
        assert imageset in self.images, f"Missing image {imageset}"
        provider = PROVIDER_IDS["gcp"]
        assert provider in self.images[imageset], f"No {provider} image for {imageset}"
        return self.images[imageset][provider]

    def build_launch_configs(
        self,
        imageset: str,
        machines: Iterable[tuple[str, frozenset[str]]],
        disk_size: int,
        platform: str,
        demand: bool,
        nested_virtualization: bool,
        performance_monitoring_unit: bool,
        max_tasks: int,
        worker_type: str,
    ) -> list[dict[str, Any]]:
        source_image = self._gcp_source_image(imageset)
        worker_config = self.get_worker_config(
            imageset,
            platform,
            max_tasks,
            worker_type,
            self.config["wst_audience"],
            self.config["wst_server_url"],
        )

        result = [
            {
                "capacityPerInstance": 1,
                "machineType": f"zones/{zone}/machineTypes/{instance}",
                "region": region,
                "zone": zone,
                "scheduling": {"onHostMaintenance": "terminate"},
                "disks": [
                    {
                        "type": "PERSISTENT",
                        "boot": True,
                        "autoDelete": True,
                        "initializeParams": {
                            "sourceImage": source_image,
                            "diskSizeGb": disk_size,
                        },
                    }
                ],
                "networkInterfaces": [{"accessConfigs": [{"type": "ONE_TO_ONE_NAT"}]}],
                "workerConfig": copy.deepcopy(worker_config),
            }
            for instance, zone_blacklist in machines
            for region, zones in self.regions.items()
            for zone in zones
            if zone not in zone_blacklist
            and not _gcp_instance_is_invalid(self.invalid_instances, zone, instance)
        ]
        for config in result:
            machine = config["machineType"].rsplit("/", 1)[-1]
            family = machine.split("-", 1)[0]
            if family in {"c4", "c4a", "c4d"} or (
                family == "c3" and machine.endswith("-metal")
            ):
                disk = config["disks"][0]
                disk["interface"] = "NVME"
                disk["initializeParams"]["diskType"] = (
                    f"zones/{config['zone']}/diskTypes/hyperdisk-balanced"
                )
        if not demand:
            for config in result:
                config["scheduling"].update(
                    {
                        "provisioningModel": "SPOT",
                        "instanceTerminationAction": "DELETE",
                    }
                )
        if nested_virtualization:
            for config in result:
                config.setdefault("advancedMachineFeatures", {})
                config["advancedMachineFeatures"]["enableNestedVirtualization"] = True
        if performance_monitoring_unit:
            for config in result:
                config.setdefault("advancedMachineFeatures", {})
                config["advancedMachineFeatures"]["performanceMonitoringUnit"] = (
                    "STANDARD"
                )
        return result


class Static(Provider):
    """Fake provider for static machines not provisioned by Taskcluster"""

    def __init__(self) -> None:
        pass

    def build_launch_configs(
        self,
        imageset: str,
        machines: Iterable[tuple[str, frozenset[str]]],
        disk_size: int,
        platform: str,
        demand: bool,
        nested_virtualization: bool,
        performance_monitoring_unit: bool,
        max_tasks: int,
        worker_type: str,
    ) -> list[dict[str, Any]]:
        return []
