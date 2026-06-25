# type: ignore
# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from pathlib import Path

import pytest

from fuzzing_decision.decision.workflow import Workflow

YAML_CONF = """---
fuzzing_config:
  path: /path/to/secret_conf
"""


def test_configure_local_defaults_to_fxci_config(tmp_path):
    """Local config without an FXCI repo setting defaults to fxci-config."""
    workflow = Workflow()

    # Fails on missing file
    with pytest.raises(AssertionError, match=r"Missing configuration in nope\.yml"):
        workflow.configure(local_path=Path("nope.yml"))

    # Read a local conf
    conf = tmp_path / "conf.yml"
    conf.write_text(YAML_CONF)
    assert workflow.configure(local_path=conf) == {
        "community_config": {
            "url": "git@github.com:mozilla-releng/fxci-config.git",
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
            "url": "git@github.com:mozilla-releng/fxci-config.git",
            "revision": "main",
        },
        "fuzzing_config": {"revision": "deadbeef", "url": "git@server:repo.git"},
    }


def test_configure_secret(mock_taskcluster_workflow):
    """Taskcluster secrets retain custom config repo URLs for compatibility."""
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
