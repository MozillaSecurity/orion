from __future__ import annotations

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from ..common.util import parse_time

LOG = logging.getLogger(__name__)


class Provider(ABC):
    def __init__(self, base_dir: Path) -> None:
        self.imagesets = yaml.safe_load(
            (base_dir / "config" / "imagesets.yml").read_text()
        )

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
        worker_type: str,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError()

    def get_worker_config(
        self, worker: str, platform: str, worker_type: str
    ) -> dict[str, Any]:
        assert worker in self.imagesets, f"Missing worker {worker}"
        out: dict[str, Any] = self.imagesets[worker].get("workerConfig", {})

        # worker implementation might be generic-worker or docker-worker
        # although we also support d2g (docker payload on generic worker)
        # so check explicitly for the worker implementation declared
        worker_impl = self.imagesets[worker]["workerImplementation"]
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

            # Fixed config for websocket tunnel
            out["genericWorker"]["config"].update(
                {
                    "wstAudience": "communitytc",
                    "wstServerURL": (
                        "https://community-websocktunnel.services.mozilla.com"
                    ),
                }
            )
            if worker_type == "d2g":
                out["genericWorker"]["config"].setdefault("d2gConfig", {})
                out["genericWorker"]["config"]["d2gConfig"]["enableD2G"] = True

            # Add a deploymentId by hashing the config
            payload = json.dumps(out, sort_keys=True).encode("utf-8")
            out["genericWorker"]["config"]["deploymentId"] = hashlib.sha256(
                payload
            ).hexdigest()[:16]

            # Clear any Docker specific config
            out.pop("dockerConfig", None)
            out.pop("shutdown", None)

        return out


class AWS(Provider):
    """Amazon Cloud provider config for Taskcluster"""

    def __init__(self, base_dir: Path) -> None:
        # Load configuration from cloned community config
        super().__init__(base_dir)
        self.regions = self.load_regions(base_dir / "config" / "aws.yml")
        LOG.info("Loaded AWS configuration")

    def load_regions(self, path: Path) -> dict[str, Any]:
        """Load AWS regions from community tc file"""
        aws = yaml.safe_load(path.read_text())
        assert "subnets" in aws, "Missing subnets in AWS config"
        assert "security_groups" in aws, "Missing security_groups in AWS config"
        assert aws["subnets"].keys() == aws["security_groups"].keys(), (
            "Keys mismatch in AWS config"
        )
        return {
            region: {
                "subnets": subnets,
                "security_groups": aws["security_groups"][region],
            }
            for region, subnets in aws["subnets"].items()
        }

    def get_amis(self, worker: str):
        assert worker in self.imagesets, f"Missing worker {worker}"
        return self.imagesets[worker]["aws"]["amis"]

    def build_launch_configs(
        self,
        imageset: str,
        machines: Iterable[tuple[str, frozenset[str]]],
        disk_size: int,
        platform: str,
        demand: bool,
        nested_virtualization: bool,
        performance_monitoring_unit: bool,
        worker_type: str,
    ) -> list[dict[str, Any]]:
        assert not nested_virtualization
        assert not performance_monitoring_unit
        # Load the AWS infos for that imageset
        amis = self.get_amis(imageset)
        worker_config = self.get_worker_config(imageset, platform, worker_type)

        result: list[dict[str, Any]] = [
            {
                "capacityPerInstance": 1,
                "region": region_name,
                "launchConfig": {
                    "ImageId": amis[region_name],
                    "Placement": {"AvailabilityZone": az},
                    "SubnetId": subnet,
                    "SecurityGroupIds": [
                        # Always use the no-inbound sec group
                        region["security_groups"]["no-inbound"]
                    ],
                    "InstanceType": instance,
                    "BlockDeviceMappings": [
                        {
                            "DeviceName": "/dev/sda1",
                            "Ebs": {
                                "VolumeSize": disk_size,
                                "VolumeType": "gp3",
                                "DeleteOnTermination": True,
                            },
                        }
                    ],
                },
                "workerConfig": worker_config,
            }
            for instance, az_blacklist in machines
            for region_name, region in self.regions.items()
            for az, subnet in region["subnets"].items()
            if region_name in amis and az not in az_blacklist
        ]
        if not demand:
            for config in result:
                config["launchConfig"]["InstanceMarketOptions"] = {"MarketType": "spot"}
        return result


class Azure(Provider):
    """Azure Cloud provider config for Taskcluster"""

    def __init__(self, base_dir: Path) -> None:
        # Load configuration from cloned community config
        super().__init__(base_dir)
        self.locations = self.load_locations(base_dir / "config" / "azure.yml")
        LOG.info("Loaded Azure configuration")

    def load_locations(self, path: Path) -> dict[str, Any]:
        """Load Azure regions from community tc file"""
        data = yaml.safe_load(path.read_text())
        assert "subnets" in data, "Missing subnets in Azure config"
        return {location: subnet for location, subnet in data["subnets"].items()}

    def get_images(self, worker: str):
        assert worker in self.imagesets, f"Missing worker {worker}"
        return self.imagesets[worker]["azure"]["images"]

    def build_launch_configs(
        self,
        imageset: str,
        machines: Iterable[tuple[str, frozenset[str]]],
        disk_size: int,
        platform: str,
        demand: bool,
        nested_virtualization: bool,
        performance_monitoring_unit: bool,
        worker_type: str,
    ) -> list[dict[str, Any]]:
        assert not nested_virtualization
        assert not performance_monitoring_unit
        # Load the Azure infos for that imageset
        images = self.get_images(imageset)
        worker_config = self.get_worker_config(imageset, platform, worker_type)

        result: list[dict[str, Any]] = [
            {
                "capacityPerInstance": 1,
                "location": location,
                "storageProfile": {
                    "osDisk": {
                        "osType": "Windows",
                        "caching": "ReadOnly",
                        "createOption": "FromImage",
                        "diffDiskSettings": {
                            "option": "Local",
                        },
                    },
                    "imageReference": {
                        "id": images[location],
                    },
                },
                "osProfile": {
                    "windowsConfiguration": {
                        "timeZone": "UTC",
                        "enableAutomaticUpdates": False,
                    },
                },
                "subnetId": subnet,
                "hardwareProfile": {
                    "vmSize": instance,
                },
                "workerConfig": worker_config,
            }
            for instance, az_blacklist in machines
            for location, subnet in self.locations.items()
            if location in images and location not in az_blacklist
        ]
        if not demand:
            for config in result:
                config.update(
                    {
                        "priority": "spot",
                        "evictionPolicy": "Delete",
                    }
                )
        return result


class GCP(Provider):
    """Google Cloud provider config for Taskcluster"""

    def __init__(self, base_dir: Path) -> None:
        # Load configuration from cloned community config
        super().__init__(base_dir)
        gcp_config = yaml.safe_load((base_dir / "config" / "gcp.yml").read_text())
        assert "regions" in gcp_config, "Missing regions in gcp config"
        self.regions = {
            region: [f"{region}-{zone}" for zone in details["zones"]]
            for region, details in gcp_config["regions"].items()
        }
        LOG.info("Loaded GCP configuration")

    def build_launch_configs(
        self,
        imageset: str,
        machines: Iterable[tuple[str, frozenset[str]]],
        disk_size: int,
        platform: str,
        demand: bool,
        nested_virtualization: bool,
        performance_monitoring_unit: bool,
        worker_type: str,
    ) -> list[dict[str, Any]]:
        # Load source image
        assert imageset in self.imagesets, f"Missing imageset {imageset}"
        assert "gcp" in self.imagesets[imageset], (
            f"No GCP implementation for imageset {imageset}"
        )
        source_image = self.imagesets[imageset]["gcp"]["image"]
        worker_config = self.get_worker_config(imageset, platform, worker_type)

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
                "workerConfig": worker_config,
            }
            for instance, zone_blacklist in machines
            for region, zones in self.regions.items()
            for zone in zones
            if zone not in zone_blacklist
        ]
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
        worker_type: str,
    ) -> list[dict[str, Any]]:
        return []
