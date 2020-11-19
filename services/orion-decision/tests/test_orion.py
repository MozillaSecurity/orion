# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Tests for Orion service classes"""

from pathlib import Path

from orion_decision.orion import Service, Services


FIXTURES = (Path(__file__).parent / "fixtures").resolve()


def test_service_load01():
    """test that service is loaded from metadata"""
    root = FIXTURES / "services01"
    svc = Service.from_metadata_yaml(root / "test" / "service.yaml", root)
    assert svc.dockerfile == root / "test" / "Dockerfile"
    assert svc.context == root
    assert svc.name == "test-image1"
    # these are calculated by `Services`, so should be clear
    assert svc.service_deps == set()
    assert svc.path_deps == set()
    assert not svc.dirty


def test_service_load02(mocker):
    """test that service is loaded from metadata"""
    mocker.patch("orion_decision.orion.machine", autospec=True, return_value="monkey")
    root = FIXTURES / "services02"
    svc = Service.from_metadata_yaml(root / "test" / "service.yaml", root)
    assert svc.dockerfile == root / "test" / "monkey" / "Dockerfile"
    assert svc.context == root
    assert svc.name == "test-image2"
    # these are calculated by `Services`, so should be clear
    assert svc.service_deps == set()
    assert svc.path_deps == set()
    assert not svc.dirty


def test_service_deps():
    """test that service dependencies are calculated and changes propagated"""
    root = FIXTURES / "services03"
    svcs = Services(root)
    assert len(svcs) == 3
    assert set(svcs) == {"test1", "test2", "test3"}
    # these are calculated by changed paths, so should be clear
    assert not svcs["test1"].dirty
    assert not svcs["test2"].dirty
    assert not svcs["test3"].dirty

    # check that deps are calculated
    assert svcs["test1"].service_deps == set()
    assert svcs["test2"].service_deps == {"test1"}
    assert svcs["test3"].service_deps == set()
    assert svcs["test1"].path_deps == {
        root / "recipes" / "linux" / "install.sh",
        root / "test1" / "Dockerfile",
        root / "test1" / "data" / "file",
        root / "test1" / "service.yaml",
    }
    assert svcs["test2"].path_deps == {
        root / "test2" / "Dockerfile",
        root / "test2" / "service.yaml",
    }
    assert svcs["test3"].path_deps == {
        root / "test3" / "Dockerfile",
        root / "test3" / "service.yaml",
    }

    # test that if install.sh changes, both images are marked dirty, script.sh is
    # skipped as a test
    svcs.mark_changed_dirty(
        [
            root / "recipes" / "linux" / "tests" / "script.sh",
            root / "recipes" / "linux" / "install.sh",
        ]
    )
    assert svcs["test1"].dirty
    assert svcs["test2"].dirty
    assert not svcs["test3"].dirty

    # test that change to files in test3 mark test3 dirty
    svcs.mark_changed_dirty([root / "test3" / "Dockerfile"])
    assert svcs["test1"].dirty
    assert svcs["test2"].dirty
    assert svcs["test3"].dirty
