# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Tests for Orion service classes"""

from pathlib import Path

import pytest
from yaml import safe_load as yaml_load

from orion_decision.orion import Service, Services, ServiceTest, ToxServiceTest

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
    assert svc.tests == []
    assert svc.root == root / "test"
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
    assert svc.tests == []
    assert svc.root == root / "test"
    assert not svc.dirty


def test_service_load03():
    """test that service tests are loaded from metadata"""
    root = FIXTURES / "services04"
    svc = Service.from_metadata_yaml(root / "test" / "service.yaml", root)
    assert svc.dockerfile == root / "test" / "Dockerfile"
    assert svc.context == root
    assert svc.name == "test-image1"
    # these are calculated by `Services`, so should be clear
    assert svc.service_deps == set()
    assert svc.path_deps == set()
    assert svc.root == root / "test"
    assert not svc.dirty
    assert len(svc.tests) == 1
    assert isinstance(svc.tests[0], ToxServiceTest)
    assert svc.tests[0].name == "test-test"
    assert svc.tests[0].image == "test-test-image"
    assert svc.tests[0].toxenv == "toxenvpy3"
    task = {"payload": {}}
    svc.tests[0].update_task(
        task, "{clone_url}", "{branch}", "{commit}", "/path/to/test"
    )
    assert "command" in task["payload"]
    assert "{clone_url}" in task["payload"]["command"][-1]
    assert "{branch}" in task["payload"]["command"][-1]
    assert "{commit}" in task["payload"]["command"][-1]
    assert "/path/to/test" in task["payload"]["command"][-1]


@pytest.mark.parametrize(
    "defn", yaml_load((FIXTURES / "services05" / "service.yaml").read_text())["tests"]
)
def test_service_load04(defn):
    """test that service test errors are raised"""
    expect = defn.pop("expect")
    if "raises" in expect:
        with pytest.raises(eval(expect["raises"]["_type"])) as exc:
            ServiceTest.from_defn(defn)
        assert expect["raises"]["msg"] in str(exc)
    else:
        result = ServiceTest.from_defn(defn)
        assert isinstance(result, eval(expect["_type"]))
        for field, value in expect["object"].items():
            assert getattr(result, field) == value


@pytest.mark.parametrize(
    "dirty_paths,expect_services,expect_recipes",
    (
        # test that if install.sh changes, images that use it are marked dirty,
        # script.sh is skipped as a test
        (
            [
                Path("recipes") / "linux" / "tests" / "script.sh",
                Path("recipes") / "linux" / "install.sh",
            ],
            {"test1", "test2", "test4"},
            {"install.sh"},
        ),
        # test that change to files in test3 mark test3 dirty
        (
            [Path("test3") / "Dockerfile"],
            {"test3"},
            set(),
        ),
        # test that change to files in test5 mark `withdep` recipe dirty
        # test6 marked dirty because it uses `withdep`
        # test7 marked dirty because it forces a dep on test5
        (
            [Path("test5") / "Dockerfile"],
            {"test5", "test6", "test7"},
            {"withdep.sh"},
        ),
    ),
)
def test_service_deps(mocker, dirty_paths, expect_services, expect_recipes):
    """test that service dependencies are calculated and changes propagated"""
    root = FIXTURES / "services03"
    repo = mocker.Mock(spec="orion_decision.git.GitRepo")
    repo.path = root
    repo.git = mocker.Mock(return_value="\n".join(str(p) for p in root.glob("**/*")))
    svcs = Services(repo)
    assert set(svcs) == {"test1", "test2", "test3", "test4", "test5", "test6", "test7"}
    assert set(svcs.recipes) == {"recipe_data", "install.sh", "withdep.sh"}
    assert len(svcs) == 7
    # these are calculated by changed paths, so should be clear
    assert not svcs["test1"].dirty
    assert not svcs["test2"].dirty
    assert not svcs["test3"].dirty
    assert not svcs["test4"].dirty
    assert not svcs["test5"].dirty
    assert not svcs["test6"].dirty
    assert not svcs["test7"].dirty
    assert not svcs.recipes["recipe_data"].dirty
    assert not svcs.recipes["install.sh"].dirty
    assert not svcs.recipes["withdep.sh"].dirty

    # check that deps are calculated
    assert svcs["test1"].service_deps == set()
    assert svcs["test2"].service_deps == {"test1"}
    assert svcs["test3"].service_deps == set()
    assert svcs["test4"].service_deps == set()
    assert svcs["test5"].service_deps == set()
    assert svcs["test6"].service_deps == set()
    assert svcs["test7"].service_deps == {"test5"}  # via direct dep
    assert svcs["test1"].path_deps == {
        root / "common" / "script.sh",
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
    assert svcs["test4"].path_deps == {
        root / "test4" / "Dockerfile",
        root / "test4" / "service.yaml",
    }
    assert svcs["test5"].path_deps == {
        root / "test5" / "Dockerfile",
        root / "test5" / "service.yaml",
    }
    assert svcs["test6"].path_deps == {
        root / "test6" / "Dockerfile",
        root / "test6" / "service.yaml",
    }
    assert svcs["test7"].path_deps == {
        root / "test7" / "Dockerfile",
        root / "test7" / "service.yaml",
    }
    assert svcs["test1"].recipe_deps == {"install.sh"}
    assert svcs["test2"].recipe_deps == set()
    assert svcs["test3"].recipe_deps == set()
    assert svcs["test4"].recipe_deps == {"install.sh"}
    assert svcs["test5"].recipe_deps == set()
    assert svcs["test6"].recipe_deps == {"withdep.sh"}
    assert svcs["test7"].recipe_deps == set()
    assert svcs.recipes["recipe_data"].service_deps == set()
    assert svcs.recipes["install.sh"].service_deps == set()
    assert svcs.recipes["withdep.sh"].service_deps == {"test5"}
    assert svcs.recipes["recipe_data"].path_deps == {
        root / "recipes" / "linux" / "recipe_data"
    }
    assert svcs.recipes["install.sh"].path_deps == {
        root / "recipes" / "linux" / "install.sh"
    }
    assert svcs.recipes["withdep.sh"].path_deps == {
        root / "recipes" / "linux" / "withdep.sh"
    }
    assert svcs.recipes["recipe_data"].recipe_deps == set()
    assert svcs.recipes["install.sh"].recipe_deps == set()
    assert svcs.recipes["withdep.sh"].recipe_deps == set()

    svcs.mark_changed_dirty([root / path for path in dirty_paths])
    for svc in svcs:
        if svc in expect_services:
            assert svcs[svc].dirty
        else:
            assert not svcs[svc].dirty
    for rec in svcs.recipes:
        if rec in expect_recipes:
            assert svcs.recipes[rec].dirty
        else:
            assert not svcs.recipes[rec].dirty


def test_services_force_dirty(mocker):
    root = FIXTURES / "services10"
    repo = mocker.Mock(spec="orion_decision.git.GitRepo")
    repo.path = root
    repo.git = mocker.Mock(return_value="\n".join(str(p) for p in root.glob("**/*")))
    svcs = Services(repo)
    assert set(svcs) == {"test1"}
    assert set(svcs.recipes) == {"setup.sh"}
    assert len(svcs) == 1

    # check that deps are calculated
    assert not svcs["test1"].service_deps
    assert not svcs["test1"].weak_deps
    assert not svcs["test1"].recipe_deps
    assert not svcs.recipes["setup.sh"].service_deps
    assert not svcs.recipes["setup.sh"].recipe_deps
    assert svcs.recipes["setup.sh"].weak_deps == {"test1"}

    svcs.mark_changed_dirty([svcs["test1"].dockerfile])
    assert svcs["test1"].dirty
    assert svcs.recipes["setup.sh"].dirty


def test_services_repo(mocker):
    """test that local services (not known to git) are ignored"""
    root = FIXTURES / "services03"
    repo = mocker.Mock(spec="orion_decision.git.GitRepo")
    repo.path = root
    repo.git = mocker.Mock(
        return_value="\n".join(
            str(p) for p in root.glob("**/*") if "test3" not in str(p)
        )
    )
    svcs = Services(repo)
    assert set(svcs) == {"test1", "test2", "test4", "test5", "test6", "test7"}
    assert len(svcs) == 6


@pytest.mark.parametrize("fixture", ["services07", "services09"])
def test_service_circular_deps(mocker, fixture):
    """test that circular service dependencies raise an error"""
    root = FIXTURES / fixture
    repo = mocker.Mock(spec="orion_decision.git.GitRepo")
    repo.path = root
    repo.git = mocker.Mock(return_value="\n".join(str(p) for p in root.glob("**/*")))
    with pytest.raises(RuntimeError) as exc:
        Services(repo)
    assert "cycle" in str(exc)


def test_service_path_dep_top_level(mocker):
    """test that similarly named files at top-level don't affect service deps"""
    root = FIXTURES / "services08"
    repo = mocker.Mock(spec="orion_decision.git.GitRepo")
    repo.path = root
    repo.git = mocker.Mock(return_value="\n".join(str(p) for p in root.glob("**/*")))
    svcs = Services(repo)
    assert set(svcs) == {"test1"}
    svcs.mark_changed_dirty([root / "setup.py"])
    assert not svcs["test1"].dirty
