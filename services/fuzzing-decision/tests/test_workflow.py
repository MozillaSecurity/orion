# type: ignore
# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import re
from pathlib import Path

import pytest
import yaml

from fuzzing_decision.decision.workflow import Workflow

YAML_CONF = """---
fuzzing_config:
  path: /path/to/secret_conf
"""


def test_patterns(tmp_path):
    # Write community fuzzing config
    conf = tmp_path / "config" / "projects" / "fuzzing.yml"
    conf.parent.mkdir(parents=True)
    conf.write_text(
        yaml.dump(
            {
                "fuzzing": {
                    "workerPools": {"pool-A": {}, "ci": {}},
                    "grants": [{"grant": [], "to": ["hook-id:project-fuzzing/B"]}],
                }
            }
        )
    )

    # Build resources patterns using that configuration
    workflow = Workflow()
    workflow.community_config_dir = tmp_path
    patterns = workflow.build_resources_patterns()
    assert patterns == [
        "Hook=project-fuzzing/.*",
        "WorkerPool=proj-fuzzing/(?!(ci|pool-A)$)",
        "Role=hook-id:project-fuzzing/(?!(B)$)",
    ]

    def _match(test):
        return any([re.match(pattern, test) for pattern in patterns])

    # Check all fuzzing hooks are managed
    assert not _match("Hook=project-another/something")
    assert _match("Hook=project-fuzzing/XXX")
    assert _match("Hook=project-fuzzing/X-Y_Z")

    # Check our pools are managed, avoiding the community ones
    assert _match("WorkerPool=proj-fuzzing/AAAA")
    assert not _match("WorkerPool=proj-fuzzing/ci")
    assert not _match("WorkerPool=proj-fuzzing/pool-A")
    assert _match("WorkerPool=proj-fuzzing/pool-B")
    assert _match("WorkerPool=proj-fuzzing/ci-bis")


def test_configure_local(tmp_path):
    workflow = Workflow()

    # Fails on missing file
    with pytest.raises(AssertionError, match="Missing configuration in nope.yml"):
        workflow.configure(local_path=Path("nope.yml"))

    # Read a local conf
    conf = tmp_path / "conf.yml"
    conf.write_text(YAML_CONF)
    assert workflow.configure(local_path=conf) == {
        "community_config": {
            "url": "git@github.com:taskcluster/community-tc-config.git",
            "revision": "main",
        },
        "fuzzing_config": {"path": "/path/to/secret_conf"},
    }

    # Check override for fuzzing repo & revision
    assert workflow.configure(
        local_path=conf,
        fuzzing_git_repository="git@server:repo.git",
        fuzzing_git_revision="deadbeef",
    ) == {
        "community_config": {
            "url": "git@github.com:taskcluster/community-tc-config.git",
            "revision": "main",
        },
        "fuzzing_config": {"revision": "deadbeef", "url": "git@server:repo.git"},
    }


def test_configure_secret(mock_taskcluster_workflow):
    workflow = mock_taskcluster_workflow

    # Read a remote conf from Taskcluster secret
    assert workflow.configure(secret="mock-fuzzing-tc") == {
        "community_config": {"url": "git@github.com:projectA/repo.git"},
        "fuzzing_config": {"url": "git@github.com:projectB/repo.git"},
        "private_key": "ssh super secret",
    }

    # Check override for fuzzing repo & revision
    assert workflow.configure(
        secret="mock-fuzzing-tc",
        fuzzing_git_repository="git@server:repo.git",
        fuzzing_git_revision="deadbeef",
    ) == {
        "community_config": {"url": "git@github.com:projectA/repo.git"},
        "fuzzing_config": {"revision": "deadbeef", "url": "git@server:repo.git"},
        "private_key": "ssh super secret",
    }
