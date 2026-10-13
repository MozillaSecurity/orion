# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

"""Per-Taskcluster-instance configuration, selected from TASKCLUSTER_ROOT_URL.

Supports running against community-tc and fxci in parallel during migration;
defaults to community-tc.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

LOG = logging.getLogger(__name__)

COMMUNITY_TC = "https://community-tc.services.mozilla.com"
FIREFOX_CI_TC = "https://firefox-ci-tc.services.mozilla.com"

DEFAULT_ROOT_URL = COMMUNITY_TC


@dataclass(frozen=True)
class Instance:
    name: str
    root_url: str
    provider_ids: dict[str, str]  # cloud (aws/azure/gcp) -> worker-manager providerId
    wst_audience: str
    wst_server_url: str
    config_layout: str  # "community" or "fxci" cloud/image config repo layout
    # GCP regions fuzzing uses (fxci only; community uses all regions in gcp.yml)
    gcp_regions: tuple[str, ...] = ()


INSTANCES: dict[str, Instance] = {
    COMMUNITY_TC: Instance(
        name="community-tc",
        root_url=COMMUNITY_TC,
        provider_ids={
            "aws": "community-tc-workers-aws",
            "azure": "community-tc-workers-azure",
            "gcp": "community-tc-workers-google",
        },
        wst_audience="communitytc",
        wst_server_url="https://community-websocktunnel.services.mozilla.com",
        config_layout="community",
    ),
    FIREFOX_CI_TC: Instance(
        name="fxci",
        root_url=FIREFOX_CI_TC,
        provider_ids={
            "aws": "aws",
            "azure": "azure2",
            "gcp": "fxci-level1-gcp",
        },
        wst_audience="firefoxci",
        wst_server_url="https://firefoxci-websocktunnel.services.mozilla.com",
        config_layout="fxci",
        gcp_regions=("us-central1", "us-west1"),  # fxci-config default-gcp-regions
    ),
}


def current_root_url() -> str:
    return os.environ.get("TASKCLUSTER_ROOT_URL", DEFAULT_ROOT_URL).rstrip("/")


def current_instance() -> Instance:
    root = current_root_url()
    instance = INSTANCES.get(root)
    if instance is None:
        LOG.warning("Unknown TASKCLUSTER_ROOT_URL %r; assuming community-tc", root)
        return INSTANCES[COMMUNITY_TC]
    return instance
