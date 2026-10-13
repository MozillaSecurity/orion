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
from fuzzing_decision.decision.instances import FIREFOX_CI_TC
from fuzzing_decision.decision.pool import build_resources
from fuzzing_decision.decision.providers import FxciAWS, FxciAzure, FxciGCP, Static
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
def test_fxci_gcp_pool(monkeypatch, mock_machines):
    monkeypatch.setenv("TASKCLUSTER_ROOT_URL", FIREFOX_CI_TC)
    clouds = {"gcp": FxciGCP(FXCI_DIR), "static": Static()}
    conf = _pool("gcp", "x64", "gcp1", "d2g", "fuzzing-gw-ubuntu-24-04")
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
        assert gw["wstAudience"] == "firefoxci"
        assert gw["wstServerURL"] == (
            "https://firefoxci-websocktunnel.services.mozilla.com"
        )
        assert gw["d2gConfig"]["enableD2G"] is True


@pytest.mark.usefixtures("appconfig")
@pytest.mark.parametrize("cloud, cpu, machine", [("aws", "arm64", "aws1")])
def test_fxci_cloud_unsupported(monkeypatch, mock_machines, cloud, cpu, machine):
    monkeypatch.setenv("TASKCLUSTER_ROOT_URL", FIREFOX_CI_TC)
    clouds = {
        "aws": FxciAWS(FXCI_DIR),
        "azure": FxciAzure(FXCI_DIR),
        "static": Static(),
    }
    conf = _pool(cloud, cpu, machine, "generic", "whatever")
    with pytest.raises(NotImplementedError):
        list(build_resources([conf], clouds, mock_machines, env=None))


@pytest.mark.usefixtures("appconfig")
def test_fxci_generate_manages_exact_ids(monkeypatch, tmp_path):
    """On fxci, generate() manages only the exact IDs it generates (never a broad
    namespace), so it can't delete fxci-config-managed infra pools."""
    monkeypatch.setenv("TASKCLUSTER_ROOT_URL", FIREFOX_CI_TC)
    (tmp_path / "machines.yml").write_text(MACHINES_YAML)
    (tmp_path / "pool1.yml").write_text(POOL_YAML)

    workflow = Workflow()
    workflow.community_config_dir = FXCI_DIR
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
