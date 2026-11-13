# type: ignore
# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import asyncio
import copy
import shutil
from pathlib import Path

import dateutil.parser
import pytest
import yaml
from tcadmin.resources import Resources

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
    """FXCI GCP pools use configured regions and combine defaults with pool settings."""
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
    # us-west1-b is zone-blacklisted (machines.yml); the other configured zones
    # remain available, including the additional europe-west4 fixture region.
    assert sorted(lc["zone"] for lc in launch_configs) == [
        "europe-west4-a",
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
        # The linux-tceng profile enables D2G by default for both worker modes.
        assert gw["d2gConfig"]["enableD2G"] is True
        assert gw["livelogExecutable"] == "/usr/local/bin/livelog"
        assert gw["ed25519SigningKeyLocation"] == "/etc/generic-worker/ed25519_key"
        assert gw["enableInteractive"] is True
        assert gw["shutdownMachineOnIdle"] is True
        assert gw["shutdownMachineOnInternalError"] is True
        assert gw["taskclusterProxyExecutable"] == ("/usr/local/bin/taskcluster-proxy")
        assert gw["workerTypeMetadata"] == {
            "machine-setup": {"script": "https://example.com/bootstrap.sh"}
        }


@pytest.mark.parametrize(
    "machine",
    [
        "c4-standard-4",
        "c4a-standard-4",
        "c4d-standard-4",
        "c3-highcpu-192-metal",
        "n2-standard-4",
    ],
)
def test_fxci_gcp_boot_disk_matches_machine_requirements(machine):
    """C4 and C3 bare-metal boot disks use NVMe Hyperdisk; N2 retains defaults."""
    provider = GCP(FXCI_DIR)
    provider.regions = {"us-east1": ["us-east1-b", "us-east1-c"]}
    configs = provider.build_launch_configs(
        "fuzzing-gw-ubuntu-24-04",
        [(machine, frozenset())],
        120,
        "linux",
        True,
        False,
        False,
        1,
        "generic",
    )
    assert len(configs) == 2
    for config in configs:
        disk = config["disks"][0]
        assert disk["boot"] is True
        assert disk["autoDelete"] is True
        assert disk["initializeParams"]["diskSizeGb"] == 120
        if machine == "n2-standard-4":
            assert "interface" not in disk
            assert "diskType" not in disk["initializeParams"]
        else:
            assert disk["interface"] == "NVME"
            assert disk["initializeParams"]["diskType"] == (
                f"zones/{config['zone']}/diskTypes/hyperdisk-balanced"
            )


def test_fxci_gcp_worker_configs_are_isolated():
    """Each GCP pool gets isolated worker settings, defaults, and image metadata."""
    provider = GCP(FXCI_DIR)
    defaults_before = copy.deepcopy(provider._worker_defaults)
    images_before = copy.deepcopy(provider.images)
    args = (
        "fuzzing-gw-ubuntu-24-04",
        [("gcp1", frozenset())],
        120,
        "linux",
        True,
        False,
        False,
    )
    first_pool = provider.build_launch_configs(*args, 1, "generic")
    second_pool = provider.build_launch_configs(*args, 5, "generic")
    first = first_pool[0]["workerConfig"]["genericWorker"]["config"]
    second = second_pool[0]["workerConfig"]["genericWorker"]["config"]
    assert first["numberOfTasksToRun"] == 1
    assert second["numberOfTasksToRun"] == 5

    first["workerTypeMetadata"]["machine-setup"]["script"] = "changed"
    first["livelogExecutable"] = "changed"
    first["d2gConfig"]["enableD2G"] = False
    assert second["workerTypeMetadata"]["machine-setup"]["script"].endswith(
        "bootstrap.sh"
    )
    assert second["livelogExecutable"] == "/usr/local/bin/livelog"
    assert second["d2gConfig"]["enableD2G"] is True
    assert provider._worker_defaults == defaults_before
    assert provider.images == images_before


def test_fxci_gcp_invalid_instances_filter_zones_with_private_blacklist():
    """FXCI zone restrictions and machine-specific blacklists both filter zones."""
    provider = GCP(FXCI_DIR)
    provider.regions = {
        "us-east1": ["us-east1-b", "us-east1-c", "us-east1-d"],
        "us-west1": ["us-west1-a", "us-west1-c"],
    }
    assert provider.invalid_instances == [
        {"zones": ["us-east1-b", "us-east1-d", "us-west1-c"], "families": ["n1"]}
    ]

    launch_configs = provider.build_launch_configs(
        "fuzzing-gw-ubuntu-24-04",
        [("n1-standard-4", frozenset({"us-east1-c"}))],
        120,
        "linux",
        True,
        False,
        False,
        1,
        "generic",
    )

    # FXCI removes b, d, and west1-c for n1; the private blacklist then removes
    # the otherwise valid east1-c, leaving a valid neighboring zone.
    assert [(config["region"], config["zone"]) for config in launch_configs] == [
        ("us-west1", "us-west1-a")
    ]


def test_fxci_gcp_missing_invalid_instances_defaults_to_empty(tmp_path):
    """FXCI configs without invalid-instance rules retain legacy machine names."""
    config_dir = tmp_path / "fxci"
    shutil.copytree(FXCI_DIR, config_dir)
    environments_path = config_dir / "environments.yml"
    environments = yaml.safe_load(environments_path.read_text())
    del environments["firefoxci"]["google_config"]["invalid-instances"]
    environments_path.write_text(yaml.safe_dump(environments, sort_keys=False))

    provider = GCP(config_dir)
    launch_configs = provider.build_launch_configs(
        "fuzzing-gw-ubuntu-24-04",
        [("gcp1", frozenset()), ("2-cpus", frozenset())],
        120,
        "linux",
        True,
        False,
        False,
        1,
        "generic",
    )

    assert provider.invalid_instances == []
    assert len(launch_configs) == 8


def test_fxci_gcp_invalid_instances_match_profile_and_full_suffix():
    """Profile and suffix constraints stay specific while empty lists wildcard."""
    provider = GCP(FXCI_DIR)
    provider.regions = {
        "us-central1": ["us-central1-a"],
        "us-west1": ["us-west1-a", "us-west1-b", "us-west1-c"],
    }
    provider.invalid_instances = [
        {
            "zones": ["us-central1-a"],
            "families": ["c4d"],
            "profiles": ["highcpu"],
            "suffixes": ["lssd-metal"],
        },
        {
            "zones": ["us-west1-a"],
            "families": ["c3d"],
            "profiles": [],
            "suffixes": [],
        },
        {
            "zones": ["us-west1-b"],
            "families": ["c4d"],
            "suffixes": ["lssd"],
        },
    ]

    machines = [
        ("c4d-highcpu-8-lssd-metal", frozenset()),
        ("c4d-standard-8-lssd-metal", frozenset()),
        ("c4d-highcpu-8-lssd", frozenset()),
        ("c3d-standard-8-lssd", frozenset()),
    ]
    launch_configs = provider.build_launch_configs(
        "fuzzing-gw-ubuntu-24-04",
        machines,
        120,
        "linux",
        True,
        False,
        False,
        1,
        "generic",
    )

    assert sorted(
        (config["zone"], config["machineType"].rsplit("/", 1)[-1])
        for config in launch_configs
    ) == [
        ("us-central1-a", "c3d-standard-8-lssd"),
        ("us-central1-a", "c4d-highcpu-8-lssd"),
        ("us-central1-a", "c4d-standard-8-lssd-metal"),
        ("us-west1-a", "c4d-highcpu-8-lssd"),
        ("us-west1-a", "c4d-highcpu-8-lssd-metal"),
        ("us-west1-a", "c4d-standard-8-lssd-metal"),
        ("us-west1-b", "c3d-standard-8-lssd"),
        ("us-west1-b", "c4d-highcpu-8-lssd-metal"),
        ("us-west1-b", "c4d-standard-8-lssd-metal"),
        ("us-west1-c", "c3d-standard-8-lssd"),
        ("us-west1-c", "c4d-highcpu-8-lssd"),
        ("us-west1-c", "c4d-highcpu-8-lssd-metal"),
        ("us-west1-c", "c4d-standard-8-lssd-metal"),
    ]


@pytest.mark.usefixtures("appconfig")
def test_fxci_gcp_docker_config_does_not_include_generic_worker_defaults(mock_machines):
    """Docker GCP pools clear generic-worker defaults from the launch config."""
    conf = _pool("gcp", "x64", "gcp1", "docker", "fuzzing-gw-ubuntu-24-04")
    pool, _hook, _role = build_resources(
        [conf], {"gcp": GCP(FXCI_DIR), "static": Static()}, mock_machines, env=None
    )
    launch_configs = pool.to_json()["config"]["launchConfigs"]
    for launch_config in launch_configs:
        worker_config = launch_config["workerConfig"]
        assert "genericWorker" not in worker_config
        assert worker_config["dockerConfig"] == {
            "allowPrivileged": True,
            "allowDisableSeccomp": True,
        }
        assert worker_config["shutdown"]["afterIdleSeconds"] == parse_time("3m")


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


@pytest.mark.parametrize("blacklist_region", ["east-us-2", "eastus2"])
def test_fxci_azure2_regions_images_and_worker_config(blacklist_region):
    """Azure2 configs use regional images, fuzzing networks, and WST defaults."""
    provider = Azure(FXCI_DIR)
    launch_configs = provider.build_launch_configs(
        "fuzzing-win2022-gpu",
        [("Standard_F16s_v2", frozenset({blacklist_region}))],
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

    assert [config["location"] for config in configs] == ["centralus", "westeurope"]


def test_azure2_pool_locations_resolve_keyed_by_variants():
    """Azure pool locations follow exact and regex selectors for declared variants."""
    pool = {
        "variants": [{"kind": "gpu"}, {"kind": "ngpu"}],
        "config": {
            "locations": {
                "by-kind": {
                    "gpu": ["east-us"],
                    "g.*": ["central-us"],
                    "n.*": ["west-us"],
                    "default": ["central-us"],
                }
            }
        },
    }

    assert Azure._pool_locations(pool) == {"east-us", "west-us"}
    assert Azure._pool_locations(
        {
            "variants": [{}],
            "config": {"locations": {"by-kind": {"default": ["central-us"]}}},
        }
    ) == {"central-us"}

    hyphenated_attribute = {
        "attributes": {"pool-group": "gecko-t"},
        "variants": [{"kind": "gpu"}],
        "config": {
            "locations": {
                "by-pool-group": {
                    "gecko-.*": {"by-kind": {"gpu": ["east-us"]}},
                    "default": ["west-us"],
                }
            }
        },
    }
    assert Azure._pool_locations(hyphenated_attribute) == {"east-us"}

    ambiguous = {
        "variants": [{"kind": "gpu-v"}],
        "config": {
            "locations": {"by-kind": {"gpu-.*": ["east-us"], ".*-v": ["west-us"]}}
        },
    }
    with pytest.raises(ValueError, match="Ambiguous Azure locations selectors"):
        Azure._pool_locations(ambiguous)


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
        "westeurope",
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

    resources = Resources()
    workflow.generate(resources, {"fuzzing_config": {"path": "x"}})

    intended_ids = {
        "WorkerPool=proj-fuzzing/linux-pool1",
        "Hook=project-fuzzing/linux-pool1",
        "Role=hook-id:project-fuzzing/linux-pool1",
    }
    assert {resource.id for resource in resources} == intended_ids
    # Exercise tc-admin's MatchList semantics: matches are rooted at the start,
    # while the pattern's $ must reject IDs with extra suffixes.
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
    assert all(resources.is_managed(resource_id) for resource_id in intended_ids)
    assert not any(resources.is_managed(resource_id) for resource_id in canary_ids)


@pytest.mark.usefixtures("appconfig")
def test_static_replacement_fetches_and_deletes_only_its_old_worker_pool(
    tmp_path, monkeypatch
):
    """A static replacement retires its old pool while preserving fxci infra pools."""
    (tmp_path / "machines.yml").write_text(MACHINES_YAML)
    (tmp_path / "pool1.yml").write_text(
        POOL_YAML.replace("cloud: gcp", "cloud: static")
    )
    (tmp_path / "workers.yml").write_text(
        """\
- cloud: static
  imageset: static-workers
  machine_types: [gcp1]
  max_capacity: 1
  name: static-worker
  owner: fuzzing@example.org
"""
    )

    workflow = Workflow()
    workflow.fxci_config_dir = FXCI_DIR
    workflow.fuzzing_config_dir = tmp_path
    desired = Resources()
    workflow.generate(desired, {"fuzzing_config": {"path": "x"}})

    retired_id = "WorkerPool=proj-fuzzing/linux-pool1"
    retired_extra_id = "WorkerPool=proj-fuzzing/static-worker"
    infra_canary_id = "WorkerPool=proj-fuzzing/ci"
    assert desired.is_managed(retired_id)
    assert desired.is_managed(retired_extra_id)
    assert not any(
        resource.id in {retired_id, retired_extra_id} for resource in desired
    )
    assert not desired.is_managed(infra_canary_id)
    assert not desired.is_managed(f"{retired_id}-extra")
    assert not desired.is_managed(f"{retired_extra_id}-extra")

    api_pools = [
        {
            "workerPoolId": "proj-fuzzing/static-worker",
            "description": "old static worker pool",
            "owner": "fuzzing@example.org",
            "config": {},
            "emailOnError": False,
            "providerId": "fxci-level1-gcp",
        },
        {
            "workerPoolId": "proj-fuzzing/linux-pool1",
            "description": "old managed pool",
            "owner": "fuzzing@example.org",
            "config": {},
            "emailOnError": False,
            "providerId": "fxci-level1-gcp",
        },
        {
            "workerPoolId": "proj-fuzzing/ci",
            "description": "fxci infrastructure pool",
            "owner": "fxci@example.org",
            "config": {},
            "emailOnError": False,
            "providerId": "fxci-level1-gcp",
        },
    ]
    deleted = []

    class MockWorkerManager:
        def __init__(self, *args, **kwargs):
            pass

        async def listWorkerPools(self, query):
            return {"workerPools": api_pools}

        async def deleteWorkerPool(self, worker_pool_id):
            deleted.append(worker_pool_id)

    async def client_options():
        return {}

    from tcadmin import current
    from tcadmin.current import worker_pools as current_worker_pools
    from tcadmin.update import Updater

    monkeypatch.setattr(
        current, "fetch_fns", {"WorkerPool": current_worker_pools.fetch_worker_pools}
    )
    monkeypatch.setattr(current_worker_pools, "WorkerManager", MockWorkerManager)
    monkeypatch.setattr(current_worker_pools, "tcClientOptions", client_options)
    monkeypatch.setattr(current_worker_pools, "aiohttp_session", lambda: None)
    monkeypatch.setattr("tcadmin.update.WorkerManager", MockWorkerManager)

    updater = Updater({"rootUrl": "https://taskcluster.invalid"}, None)

    async def fetch_and_apply():
        current_resources = await current.resources(desired.managed)
        assert {resource.id for resource in current_resources} == {
            retired_id,
            retired_extra_id,
        }
        await updater.update(Resources([], desired.managed), current_resources)

    asyncio.run(fetch_and_apply())
    assert set(deleted) == {"proj-fuzzing/linux-pool1", "proj-fuzzing/static-worker"}
