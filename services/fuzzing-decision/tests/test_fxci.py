# type: ignore
# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import re
from pathlib import Path

import dateutil.parser
import pytest

from fuzzing_decision.common.pool import FuzzingPoolConfig
from fuzzing_decision.common.util import parse_time
from fuzzing_decision.decision.pool import build_resources
from fuzzing_decision.decision.providers import AWS, GCP, Azure, Static
from fuzzing_decision.decision.workflow import Workflow

FXCI_DIR = Path(__file__).parent / "fixtures" / "fxci"

POOL_YAML = """
cloud: gcp
command: [run-fuzzing.sh]
container: MozillaSecurity/fuzzer:latest
cpu: x64
cycle_time: 1h
demand: true
disk_size: 120g
env: {}
imageset: fuzzing-gw-ubuntu-24-04
machine_types: [gcp1]
max_run_time: 1h
name: fxci pool
nested_virtualization: false
parents: []
platform: linux
preprocess: null
routes: []
run_as_admin: false
schedule_start: null
scopes: []
tasks: 1
worker: d2g
"""

MACHINES_YAML = """
gcp:
  x64:
    gcp1:
      zone_blacklist: []
"""


def _pool(cloud, cpu, machine, worker, imageset) -> FuzzingPoolConfig:
    return FuzzingPoolConfig(
        apply_to=[],
        artifacts={},
        base_dir=Path.cwd(),
        cloud=cloud,
        command=["run-fuzzing.sh"],
        container="MozillaSecurity/fuzzer:latest",
        cpu=cpu,
        cycle_time=parse_time("12h"),
        demand=True,
        disk_size=120,
        env={},
        imageset=imageset,
        machine_types=[machine],
        max_run_time=parse_time("12h"),
        max_tasks=0,
        name="fxci pool",
        nested_virtualization=False,
        parents=[],
        performance_monitoring_unit=False,
        platform="linux",
        pool_id="test",
        preprocess="",
        routes=[],
        run_as_admin=False,
        schedule_start=dateutil.parser.isoparse("1970-01-01T00:00:00Z"),
        scopes=[],
        tasks=3,
        worker=worker,
    )


@pytest.mark.usefixtures("appconfig")
@pytest.mark.parametrize("worker_type", ["generic", "d2g"])
def test_fxci_gcp_pool(monkeypatch, mock_machines, worker_type):
    """FXCI GCP pools use FXCI images, supported regions, and websocktunnel."""
    # A different endpoint must not switch provider IDs or configuration layouts.
    monkeypatch.setenv(
        "TASKCLUSTER_ROOT_URL", "https://community-tc.services.mozilla.com"
    )
    clouds = {"gcp": GCP(FXCI_DIR), "static": Static()}
    conf = _pool("gcp", "x64", "gcp1", worker_type, "fuzzing-gw-ubuntu-24-04")
    pool, _hook, _role = build_resources([conf], clouds, mock_machines, env=None)
    data = pool.to_json()

    assert data["providerId"] == "fxci-level1-gcp"

    launch_configs = data["config"]["launchConfigs"]
    # us-west1-b is zone-blacklisted (machines.yml); europe-west4 is not a fuzzing
    # gcp_region -> only us-central1-a and us-west1-a remain.
    assert sorted(lc["zone"] for lc in launch_configs) == [
        "us-central1-a",
        "us-west1-a",
    ]
    for lc in launch_configs:
        image = lc["disks"][0]["initializeParams"]["sourceImage"]
        assert image == "projects/fake/global/images/fuzzing-gw-ubuntu-24-04"
        gw = lc["workerConfig"]["genericWorker"]["config"]
        assert gw["disableOOMProtection"] is True
        assert gw["maxTaskRunTime"] == parse_time("3d")
        assert gw["idleTimeoutSecs"] == parse_time("15m")
        assert gw["numberOfTasksToRun"] == 0
        assert gw["wstAudience"] == "firefoxci-gcp"
        assert gw["wstServerURL"] == ("https://gcp-websocktunnel.services.mozilla.com/")
        if worker_type == "d2g":
            assert gw["d2gConfig"]["enableD2G"] is True
        else:
            assert "d2gConfig" not in gw


@pytest.mark.usefixtures("appconfig")
def test_fxci_aws_remains_unsupported(mock_machines):
    """FXCI AWS requests remain fail closed until an AWS provider is implemented."""
    clouds = {
        "aws": AWS(FXCI_DIR),
        "azure": Azure(FXCI_DIR),
        "static": Static(),
    }
    conf = _pool("aws", "x64", "gcp1", "generic", "whatever")
    with pytest.raises(NotImplementedError):
        list(build_resources([conf], clouds, mock_machines, env=None))


def test_fxci_azure2_regions_images_and_worker_config():
    """Azure2 configs use regional images, fuzzing networks, and WST defaults."""
    provider = Azure(FXCI_DIR)
    launch_configs = provider.build_launch_configs(
        "fuzzing-win2022-gpu",
        [("Standard_F16s_v2", frozenset({"east-us-2"}))],
        disk_size=120,
        platform="windows",
        demand=True,
        nested_virtualization=False,
        performance_monitoring_unit=False,
        max_tasks=17,
        worker_type="generic",
    )

    # The GPU image is regional; the machine blacklist removes east-us-2.
    assert [config["location"] for config in launch_configs] == [
        "southcentralus",
        "westus2",
    ]
    assert all(
        config["hardwareProfile"]["vmSize"] == "Standard_F16s_v2"
        for config in launch_configs
    )
    assert all(
        config["storageProfile"]["osDisk"]["diskSizeGB"] == 120
        for config in launch_configs
    )
    assert all(
        config["storageProfile"]["osDisk"]["createOption"] == "FromImage"
        for config in launch_configs
    )
    subscription_path = "/subscriptions/108d46d5-fe9b-4850-9a7d-8c914aa6c1f0"
    assert [
        config["storageProfile"]["imageReference"]["id"] for config in launch_configs
    ] == [
        f"{subscription_path}/resourceGroups/rg-packer-worker-images/providers/"
        f"Microsoft.Compute/images/gw-win2022-{region}"
        for region in ("south-central", "west")
    ]
    assert all("priority" not in config for config in launch_configs)
    expected_locations = (
        ("southcentralus", "south-central-us"),
        ("westus2", "west-us-2"),
    )
    for config, (azure_location, region) in zip(
        launch_configs, expected_locations, strict=True
    ):
        assert config["location"] == azure_location
        assert config["subnetId"] == (
            f"{subscription_path}/resourceGroups/rg-{region}-proj-fuzzing/providers/"
            f"Microsoft.Network/virtualNetworks/vn-{region}-proj-fuzzing/"
            f"subnets/sn-{region}-proj-fuzzing"
        )
        assert config["osProfile"]["windowsConfiguration"] == {
            "timeZone": "UTC",
            "enableAutomaticUpdates": False,
        }
        gw = config["workerConfig"]["genericWorker"]["config"]
        assert gw["numberOfTasksToRun"] == 17
        assert gw["wstAudience"] == "firefoxcitc"
        assert gw["wstServerURL"] == (
            "https://firefoxci-websocktunnel.services.mozilla.com/"
        )
        assert gw["livelogExecutable"] == r"C:\generic-worker\livelog.exe"
        assert gw["ed25519SigningKeyLocation"] == (
            r"C:\generic-worker\generic-worker-ed25519-signing-key.key"
        )
        assert gw["shutdownMachineOnIdle"] is True
        assert gw["shutdownMachineOnInternalError"] is True
        assert gw["taskclusterProxyExecutable"] == (
            r"C:\generic-worker\taskcluster-proxy.exe"
        )
        assert gw["workerTypeMetadata"]["machine-setup"]["script"].endswith("setup.ps1")


def test_fxci_azure2_filters_images_by_configured_regions():
    """Azure2 ignores a regional image when FXCI disables its Azure location."""
    provider = Azure(FXCI_DIR)
    provider.allowed_locations.remove("eastus")
    configs = provider.build_launch_configs(
        "fuzzing-win2022",
        [("Standard_F16s_v2", frozenset())],
        disk_size=60,
        platform="windows",
        demand=True,
        nested_virtualization=False,
        performance_monitoring_unit=False,
        max_tasks=1,
        worker_type="generic",
    )

    assert [config["location"] for config in configs] == ["centralus"]


@pytest.mark.parametrize("demand", [True, False])
def test_fxci_azure2_demand_controls_spot_launch_fields(demand):
    """Azure2 demand pools omit spot fields while opportunistic pools request Spot."""
    configs = Azure(FXCI_DIR).build_launch_configs(
        "fuzzing-win2022",
        [("Standard_F16s_v2", frozenset())],
        disk_size=60,
        platform="windows",
        demand=demand,
        nested_virtualization=False,
        performance_monitoring_unit=False,
        max_tasks=3,
        worker_type="generic",
    )
    assert configs
    if demand:
        assert all(
            "priority" not in config
            and "billingProfile" not in config
            and "evictionPolicy" not in config
            for config in configs
        )
    else:
        assert all(config["priority"] == "spot" for config in configs)
        assert all(config["billingProfile"] == {"maxPrice": -1} for config in configs)
        assert all(config["evictionPolicy"] == "Delete" for config in configs)


def test_fxci_azure2_gallery_images_use_fxci_gallery_resource_ids():
    """Versioned Azure2 images use the FXCI shared image gallery identifier."""
    configs = Azure(FXCI_DIR).build_launch_configs(
        "fuzzing-win2025-gallery",
        [("Standard_D8s_v5", frozenset())],
        disk_size=80,
        platform="windows",
        demand=True,
        nested_virtualization=False,
        performance_monitoring_unit=False,
        max_tasks=1,
        worker_type="generic",
    )
    assert [config["location"] for config in configs] == [
        "centralus",
        "eastus",
        "eastus2",
        "southcentralus",
        "westus2",
    ]
    assert all(
        config["storageProfile"]["imageReference"]["id"].endswith(
            "/galleries/win2025_64_24h2/images/win2025_64_24h2/versions/1.3.14"
        )
        for config in configs
    )
    assert all(config["tags"] == {"deploymentId": "78fbc06"} for config in configs)


@pytest.mark.usefixtures("appconfig")
def test_fxci_azure_pool_uses_azure2_provider_id(mock_machines):
    """Generated FXCI Azure pools identify the native azure2 worker-manager provider."""
    clouds = {"azure": Azure(FXCI_DIR), "static": Static()}
    conf = _pool("azure", "x64", "azure1", "generic", "fuzzing-win2022")
    conf.platform = "windows"
    pool, _hook, _role = build_resources([conf], clouds, mock_machines, env=None)

    assert pool.to_json()["providerId"] == "azure2"
    assert pool.to_json()["config"]["launchConfigs"]


@pytest.mark.parametrize(
    ("nested_virtualization", "performance_monitoring_unit"),
    [(True, False), (False, True)],
)
def test_fxci_azure2_rejects_unsupported_machine_features(
    nested_virtualization, performance_monitoring_unit
):
    """Azure2 rejects machine features absent from its FXCI launch schema."""
    with pytest.raises(NotImplementedError, match="Azure worker pools do not support"):
        Azure(FXCI_DIR).build_launch_configs(
            "fuzzing-win2022",
            [],
            disk_size=60,
            platform="windows",
            demand=True,
            nested_virtualization=nested_virtualization,
            performance_monitoring_unit=performance_monitoring_unit,
            max_tasks=1,
            worker_type="generic",
        )


def test_fxci_azure2_missing_image_fails_with_provider_context():
    """An image without an azure2 definition fails with a useful configuration error."""
    with pytest.raises(AssertionError, match="No azure2 image for generic-worker-A"):
        Azure(FXCI_DIR).build_launch_configs(
            "generic-worker-A",
            [],
            disk_size=60,
            platform="windows",
            demand=True,
            nested_virtualization=False,
            performance_monitoring_unit=False,
            max_tasks=1,
            worker_type="generic",
        )


@pytest.mark.usefixtures("appconfig")
def test_fxci_generate_manages_exact_ids(tmp_path):
    """On fxci, generate() manages only the exact IDs it generates (never a broad
    namespace), so it can't delete fxci-config-managed infra pools."""
    (tmp_path / "machines.yml").write_text(MACHINES_YAML)
    (tmp_path / "pool1.yml").write_text(POOL_YAML)

    workflow = Workflow()
    workflow.fxci_config_dir = FXCI_DIR
    workflow.fuzzing_config_dir = tmp_path

    managed = []
    updated = []

    class FakeResources:
        def manage(self, pattern):
            managed.append(pattern)

        def update(self, resources):
            updated.extend(resources)

    workflow.generate(FakeResources(), {"fuzzing_config": {"path": "x"}})

    intended_ids = {
        "WorkerPool=proj-fuzzing/linux-pool1",
        "Hook=project-fuzzing/linux-pool1",
        "Role=hook-id:project-fuzzing/linux-pool1",
    }
    assert {resource.id for resource in updated} == intended_ids
    # Check management behavior instead of depending on one regex spelling.
    # Anchors matter: near matches and fxci-config-managed resources must remain
    # outside the managed set.
    canary_ids = {
        "unmanaged:WorkerPool=proj-fuzzing/linux-pool1",
        "WorkerPool=proj-fuzzing/linux-pool1-extra",
        "WorkerPool=proj-fuzzing/ci",
        "unmanaged:Hook=project-fuzzing/linux-pool1",
        "Hook=project-fuzzing/linux-pool1-extra",
        "Hook=project-fuzzing/other",
        "unmanaged:Role=hook-id:project-fuzzing/linux-pool1",
        "Role=hook-id:project-fuzzing/linux-pool1-extra",
        "Role=hook-id:project-fuzzing/other",
    }
    assert len(managed) == len(intended_ids)
    matched_ids = set()
    for pattern in managed:
        matches = {
            resource_id
            for resource_id in intended_ids
            if re.search(pattern, resource_id)
        }
        assert len(matches) == 1
        assert not any(re.search(pattern, resource_id) for resource_id in canary_ids)
        matched_ids.update(matches)
    assert matched_ids == intended_ids
