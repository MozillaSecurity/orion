# type: ignore
# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from pathlib import Path

import dateutil.parser
import pytest

from fuzzing_decision.common.pool import FuzzingPoolConfig
from fuzzing_decision.common.util import parse_time
from fuzzing_decision.decision.instances import (
    COMMUNITY_TC,
    FIREFOX_CI_TC,
    current_instance,
    current_root_url,
)
from fuzzing_decision.decision.pool import build_resources


def test_current_root_url_default(monkeypatch):
    monkeypatch.delenv("TASKCLUSTER_ROOT_URL", raising=False)
    assert current_root_url() == COMMUNITY_TC


def test_current_root_url_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("TASKCLUSTER_ROOT_URL", FIREFOX_CI_TC + "/")
    assert current_root_url() == FIREFOX_CI_TC


@pytest.mark.parametrize(
    "root_url, name",
    [
        (COMMUNITY_TC, "community-tc"),
        (FIREFOX_CI_TC, "fxci"),
    ],
)
def test_current_instance_known(monkeypatch, root_url, name):
    monkeypatch.setenv("TASKCLUSTER_ROOT_URL", root_url)
    assert current_instance().name == name


def test_current_instance_unset_defaults_to_community(monkeypatch):
    monkeypatch.delenv("TASKCLUSTER_ROOT_URL", raising=False)
    assert current_instance().name == "community-tc"


def test_current_instance_unknown_defaults_to_community(monkeypatch):
    monkeypatch.setenv("TASKCLUSTER_ROOT_URL", "https://example.invalid")
    assert current_instance().name == "community-tc"


def test_provider_ids_per_instance(monkeypatch):
    monkeypatch.setenv("TASKCLUSTER_ROOT_URL", COMMUNITY_TC)
    assert current_instance().provider_ids == {
        "aws": "community-tc-workers-aws",
        "azure": "community-tc-workers-azure",
        "gcp": "community-tc-workers-google",
    }
    monkeypatch.setenv("TASKCLUSTER_ROOT_URL", FIREFOX_CI_TC)
    assert current_instance().provider_ids == {
        "aws": "aws",
        "azure": "azure2",
        "gcp": "fxci-level1-gcp",
    }


def test_websocktunnel_per_instance(monkeypatch):
    monkeypatch.setenv("TASKCLUSTER_ROOT_URL", COMMUNITY_TC)
    community = current_instance()
    assert community.wst_audience == "communitytc"
    assert (
        community.wst_server_url
        == "https://community-websocktunnel.services.mozilla.com"
    )
    monkeypatch.setenv("TASKCLUSTER_ROOT_URL", FIREFOX_CI_TC)
    fxci = current_instance()
    assert fxci.wst_audience == "firefoxci"
    assert fxci.wst_server_url == "https://firefoxci-websocktunnel.services.mozilla.com"


def _generic_aws_pool() -> FuzzingPoolConfig:
    """A minimal generic-worker AWS pool, mirroring tests/test_pool.py."""
    return FuzzingPoolConfig(
        apply_to=[],
        artifacts={},
        base_dir=Path.cwd(),
        cloud="aws",
        command=["run-fuzzing.sh"],
        container="MozillaSecurity/fuzzer:latest",
        cpu="arm64",
        cycle_time=parse_time("12h"),
        demand=True,
        disk_size=120,
        env={},
        imageset="generic-worker-A",
        machine_types=["a2"],
        max_run_time=parse_time("12h"),
        max_tasks=0,
        name="fxci pool",
        nested_virtualization=False,
        parents=[],
        performance_monitoring_unit=False,
        platform="windows",
        pool_id="test",
        preprocess="",
        routes=[],
        run_as_admin=False,
        schedule_start=dateutil.parser.isoparse("1970-01-01T00:00:00Z"),
        scopes=[],
        tasks=3,
        worker="generic",
    )


@pytest.mark.usefixtures("appconfig")
def test_worker_pool_uses_instance_provider_and_wst(
    monkeypatch, mock_clouds, mock_machines
):
    """providerId and websocktunnel follow TASKCLUSTER_ROOT_URL."""
    monkeypatch.setenv("TASKCLUSTER_ROOT_URL", FIREFOX_CI_TC)
    pool, _hook, _role = build_resources(
        [_generic_aws_pool()], mock_clouds, mock_machines, env=None
    )
    data = pool.to_json()
    assert data["providerId"] == "aws"  # fxci's aws providerId
    gw_config = data["config"]["launchConfigs"][0]["workerConfig"]["genericWorker"][
        "config"
    ]
    assert gw_config["wstAudience"] == "firefoxci"
    assert (
        gw_config["wstServerURL"]
        == "https://firefoxci-websocktunnel.services.mozilla.com"
    )

    # ...and community-tc remains the default
    monkeypatch.setenv("TASKCLUSTER_ROOT_URL", COMMUNITY_TC)
    pool, _hook, _role = build_resources(
        [_generic_aws_pool()], mock_clouds, mock_machines, env=None
    )
    data = pool.to_json()
    assert data["providerId"] == "community-tc-workers-aws"
    gw_config = data["config"]["launchConfigs"][0]["workerConfig"]["genericWorker"][
        "config"
    ]
    assert gw_config["wstAudience"] == "communitytc"
