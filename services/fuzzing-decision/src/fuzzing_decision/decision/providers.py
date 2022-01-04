# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import yaml

from ..common.pool import parse_time

LOG = logging.getLogger(__name__)


class Provider(object):
    def __init__(self, base_dir: Path) -> None:
        self.imagesets = yaml.safe_load(
            (base_dir / "config" / "imagesets.yml").read_text()
        )

    def get_worker_config(self, worker, platform):
        assert worker in self.imagesets, f"Missing worker {worker}"
        out = self.imagesets[worker].get("workerConfig", {})

        if platform == "linux":
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

            # Fixed config for websocket tunnel
            out["genericWorker"]["config"].update(
                {
                    "wstAudience": "communitytc",
                    "wstServerURL": (
                        "https://community-websocktunnel.services.mozilla.com"
                    ),
                }
            )

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

    def __init__(self, base_dir) -> None:
        # Load configuration from cloned community config
        super().__init__(base_dir)
        self.regions = self.load_regions(base_dir / "config" / "aws.yml")
        LOG.info("Loaded AWS configuration")

    def load_regions(self, path):
        """Load AWS regions from community tc file"""
        aws = yaml.safe_load(path.read_text())
        assert "subnets" in aws, "Missing subnets in AWS config"
        assert "security_groups" in aws, "Missing security_groups in AWS config"
        assert (
            aws["subnets"].keys() == aws["security_groups"].keys()
        ), "Keys mismatch in AWS config"
        return {
            region: {
                "subnets": subnets,
                "security_groups": aws["security_groups"][region],
            }
            for region, subnets in aws["subnets"].items()
        }

    def get_amis(self, worker):
        assert worker in self.imagesets, f"Missing worker {worker}"
        return self.imagesets[worker]["aws"]["amis"]

    def build_launch_configs(self, imageset, machines, disk_size, platform):
        # Load the AWS infos for that imageset
        amis = self.get_amis(imageset)
        worker_config = self.get_worker_config(imageset, platform)

        return [
            {
                "capacityPerInstance": capacity,
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
                    # Always use spot instances
                    "InstanceMarketOptions": {"MarketType": "spot"},
                },
                "workerConfig": worker_config,
            }
            for instance, capacity, az_blacklist in machines
            for region_name, region in self.regions.items()
            for az, subnet in region["subnets"].items()
            if region_name in amis and az not in az_blacklist
        ]


class GCP(Provider):
    """Google Cloud provider config for Taskcluster"""

    def __init__(self, base_dir) -> None:
        # Load configuration from cloned community config
        super().__init__(base_dir)
        gcp_config = yaml.safe_load((base_dir / "config" / "gcp.yml").read_text())
        assert "regions" in gcp_config, "Missing regions in gcp config"
        self.regions = {
            region: [f"{region}-{zone}" for zone in details["zones"]]
            for region, details in gcp_config["regions"].items()
        }
        LOG.info("Loaded GCP configuration")

    def build_launch_configs(self, imageset, machines, disk_size, platform):

        # Load source image
        assert imageset in self.imagesets, f"Missing imageset {imageset}"
        assert (
            "gcp" in self.imagesets[imageset]
        ), f"No GCP implementation for imageset {imageset}"
        source_image = self.imagesets[imageset]["gcp"]["image"]
        worker_config = self.get_worker_config(imageset, platform)

        return [
            {
                "capacityPerInstance": capacity,
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
            for instance, capacity, zone_blacklist in machines
            for region, zones in self.regions.items()
            for zone in zones
            if zone not in zone_blacklist
        ]
