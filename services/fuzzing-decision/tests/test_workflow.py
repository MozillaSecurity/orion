# type: ignore
# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import re
from pathlib import Path
from shutil import copytree

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
        "WorkerPool=proj-fuzzing/(?!(ci|pool-A)$).*",
        "Role=hook-id:project-fuzzing/(?!(B)$).*",
    ]

    def _match(test):
        return any([re.fullmatch(pattern, test) for pattern in patterns])

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


@pytest.mark.usefixtures("appconfig")
def test_generate_skips_apply_to_with_all_pools_disabled(tmp_path):
    fixtures = Path(__file__).parent / "fixtures"
    community = tmp_path / "community"
    copytree(fixtures / "community", community)
    community_config = community / "config" / "projects" / "fuzzing.yml"
    community_config.parent.mkdir()
    community_config.write_text("fuzzing: {}\n")
    (tmp_path / "machines.yml").write_text((fixtures / "machines.yml").read_text())
    pool = yaml.safe_load((fixtures / "pools" / "pool1.yml").read_text())
    pool["tasks"] = 0
    (tmp_path / "pool1.yml").write_text(yaml.safe_dump(pool))
    (tmp_path / "pool2.yml").write_text("name: coverage\ntasks: 1\napply_to: [pool1]\n")

    from tcadmin.resources import Resources

    workflow = Workflow()
    workflow.community_config_dir = community
    workflow.fuzzing_config_dir = tmp_path
    resources = Resources()
    workflow.generate(resources, {"fuzzing_config": {"path": "x"}})

    assert {resource.id for resource in resources} == {
        "WorkerPool=proj-fuzzing/linux-pool1",
        "Hook=project-fuzzing/linux-pool1",
        "Role=hook-id:project-fuzzing/linux-pool1",
    }


def test_configure_local(tmp_path):
    workflow = Workflow()

    # Fails on missing file
    with pytest.raises(AssertionError, match=r"Missing configuration in nope\.yml"):
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
