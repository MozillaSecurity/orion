# -*- coding: utf-8 -*-

import json
import pathlib
from unittest.mock import Mock, patch

import pytest
import responses

from fuzzing_decision.common import taskcluster
from fuzzing_decision.common.pool import MachineTypes
from fuzzing_decision.decision.providers import AWS, GCP
from fuzzing_decision.decision.workflow import Workflow

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def mock_taskcluster_workflow():
    """Mock Taskcluster HTTP services"""

    workflow = Workflow()

    # Add a basic configuration for the workflow in a secret
    secret = {
        "community_config": {"url": "git@github.com:projectA/repo.git"},
        "fuzzing_config": {"url": "git@github.com:projectB/repo.git"},
        "private_key": "ssh super secret",
    }
    responses.add(
        responses.GET,
        "http://taskcluster.test/api/secrets/v1/secret/mock-fuzzing-tc",
        body=json.dumps({"secret": secret}),
        content_type="application/json",
    )
    with patch.dict(taskcluster.options, {"rootUrl": "http://taskcluster.test"}):
        yield workflow


@pytest.fixture
def mock_clouds():
    """Mock Cloud providers setup"""
    community = FIXTURES_DIR / "community"
    return {"aws": AWS(community), "gcp": GCP(community)}


@pytest.fixture
def mock_machines():
    """Mock a static list of machines"""
    path = FIXTURES_DIR / "machines.yml"
    assert path.exists()
    return MachineTypes.from_file(path)


@pytest.fixture(autouse=True)
def disable_cleanup():
    """Disable workflow cleanup in unit tests as tmpdir is automatically removed"""
    Workflow.cleanup = Mock()
