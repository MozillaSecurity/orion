from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ci.graph import GraphError, ServiceGraph, _dockerfile_dependencies
from ci.plan import build_plan


def make_repo(tmp_path: Path, files: dict[str, str]) -> set[str]:
    tracked = set()
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        tracked.add(name)
    return tracked


def test_multistage_dockerfile_dependencies() -> None:
    bases, copies, copy_from = _dockerfile_dependencies(
        """FROM ubuntu:24.04 AS build
COPY [\"src/a.c\", \"src/b.c\", \"/src/\"]
FROM mozillasecurity/grizzly:latest
COPY --from=build /out /out
COPY --from=mozillasecurity/toolchain:2 /tool /tool
"""
    )
    assert bases == ["ubuntu:24.04", "mozillasecurity/grizzly:latest"]
    assert copies == {"src/a.c", "src/b.c"}
    assert copy_from == {"mozillasecurity/toolchain:2"}


def test_path_recipe_and_weak_dependency_propagation(tmp_path: Path) -> None:
    tracked = make_repo(
        tmp_path,
        {
            "services/base/service.yaml": "name: base\n",
            "services/base/Dockerfile": "FROM ubuntu:24.04\n",
            "services/app/service.yaml": "name: app\n",
            "services/app/Dockerfile": (
                "FROM mozillasecurity/base:latest\n"
                "COPY services/app/assets/ /opt/assets/\n"
                "RUN setup.sh\n"
            ),
            "services/app/assets/file.txt": "payload\n",
            "services/observer/service.yaml": "name: observer\nforce_dirty: [base]\n",
            "services/observer/Dockerfile": "FROM ubuntu:24.04\n",
            "recipes/linux/setup.sh": "#!/bin/sh\n# /force-deps=base\n",
        },
    )
    graph = ServiceGraph(tmp_path, tracked)
    dirty = graph.mark_dirty(["services/app/assets/file.txt"])
    assert dirty == ["app"]
    assert graph.services["app"].dependencies == {"base"}
    assert graph.services["app"].image_dependencies == {"base"}

    graph = ServiceGraph(tmp_path, tracked)
    dirty = graph.mark_dirty(["services/base/Dockerfile"])
    assert dirty == ["app", "base", "observer"]


def test_recipe_change_marks_users_and_reports_recipe(tmp_path: Path) -> None:
    tracked = make_repo(
        tmp_path,
        {
            "services/app/service.yaml": "name: app\n",
            "services/app/Dockerfile": "FROM ubuntu:24.04\nRUN setup.sh\n",
            "recipes/linux/setup.sh": "#!/bin/sh\n",
        },
    )
    plan = ServiceGraph(tmp_path, tracked).plan(["recipes/linux/setup.sh"])
    assert plan["dirty"] == ["app"]
    assert plan["recipes"] == ["setup.sh"]


def test_deleted_copy_input_still_marks_service_dirty(tmp_path: Path) -> None:
    tracked = make_repo(
        tmp_path,
        {
            "services/app/service.yaml": "name: app\n",
            "services/app/Dockerfile": (
                "FROM ubuntu:24.04\nCOPY removed.dat /opt/removed.dat\n"
            ),
        },
    )
    graph = ServiceGraph(tmp_path, tracked)
    assert graph.mark_dirty(["removed.dat"]) == ["app"]


@pytest.mark.parametrize(
    "changed",
    [
        "services/app/nested/deleted.txt",
        "shared/data/deleted.txt",
        "shared/assets/icon.svg",
    ],
)
def test_deleted_nested_or_globbed_path_marks_service_dirty(
    tmp_path: Path, changed: str
) -> None:
    tracked = make_repo(
        tmp_path,
        {
            "services/app/service.yaml": "name: app\n",
            "services/app/Dockerfile": (
                "FROM ubuntu:24.04\n"
                "COPY shared/assets/*.svg /opt/assets/\n"
                "COPY shared/data/ /opt/data/\n"
            ),
            "services/app/nested/kept.txt": "payload\n",
        },
    )
    graph = ServiceGraph(tmp_path, tracked)
    assert graph.mark_dirty([changed]) == ["app"]


def test_deleted_recipe_still_marks_referencing_service(tmp_path: Path) -> None:
    tracked = make_repo(
        tmp_path,
        {
            "services/app/service.yaml": "name: app\n",
            "services/app/Dockerfile": "FROM ubuntu:24.04\nRUN removed-setup.sh\n",
        },
    )
    graph = ServiceGraph(tmp_path, tracked)
    assert graph.mark_dirty(["recipes/linux/removed-setup.sh"]) == ["app"]


def test_plan_flattens_tests_and_resolves_head_sha(tmp_path: Path) -> None:
    make_repo(
        tmp_path,
        {
            "service.yaml": (
                "name: lint\ntype: test\ntests:\n  - name: lint\n"
                "    type: tox\n    python: '3.10'\n    toxenv: lint\n"
            ),
            "README.md": "first\n",
        },
    )
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "service.yaml", "README.md"], check=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "initial",
        ],
        check=True,
    )
    base = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (tmp_path / "README.md").write_text("changed\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "update",
        ],
        check=True,
    )
    head = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    plan = build_plan(tmp_path, base=base)
    assert plan["head"] == head
    assert plan["revision"] == head
    assert plan["base"] == base
    assert plan["changed_paths"] == ["README.md"]
    assert plan["dirty"] == ["lint"]
    assert plan["test_matrix"] == [
        {
            "service": "lint",
            "path": ".",
            "python": "3.10",
            "toxenv": "lint",
            "name": "lint",
        }
    ]


def test_nested_test_matrix_uses_service_directory(tmp_path: Path) -> None:
    tracked = make_repo(
        tmp_path,
        {
            "services/nyx/symbol-filter/service.yaml": (
                "name: symbol-filter\ntype: test\ntests:\n"
                "  - name: py310\n    python: '3.10'\n    toxenv: py310\n"
            ),
            "services/nyx/symbol-filter/module.py": "pass\n",
        },
    )
    plan = ServiceGraph(tmp_path, tracked).plan(
        ["services/nyx/symbol-filter/module.py"]
    )
    assert plan["test_matrix"][0]["path"] == "services/nyx/symbol-filter"


def test_root_test_does_not_dirty_on_nested_service_change(tmp_path: Path) -> None:
    tracked = make_repo(
        tmp_path,
        {
            "service.yaml": "name: orion\ntype: test\n",
            "README.md": "root file\n",
            "services/bugmon/service.yaml": "name: bugmon\n",
            "services/bugmon/Dockerfile": "FROM ubuntu:24.04\n",
            "services/bugmon/launch.sh": "echo bugmon\n",
            "services/afl/service.yaml": "name: afl\n",
            "services/afl/Dockerfile": "FROM ubuntu:24.04\n",
        },
    )
    plan = ServiceGraph(tmp_path, tracked).plan(["services/bugmon/launch.sh"])
    assert plan["dirty"] == ["bugmon"]
    assert plan["services"]["orion"]["dirty"] is False


def test_recipe_dependencies_are_flattened_into_service_needs(tmp_path: Path) -> None:
    tracked = make_repo(
        tmp_path,
        {
            "services/base/service.yaml": "name: base\n",
            "services/base/Dockerfile": "FROM ubuntu:24.04\n",
            "services/app/service.yaml": "name: app\n",
            "services/app/Dockerfile": "FROM ubuntu:24.04\nRUN setup.sh\n",
            "recipes/linux/setup.sh": "#!/bin/sh\n# /force-deps=base\n",
        },
    )
    graph = ServiceGraph(tmp_path, tracked)
    assert graph.services["app"].dependencies == {"base"}
    assert graph.services["app"].image_dependencies == set()
    assert graph.mark_dirty(["services/base/Dockerfile"]) == ["app", "base"]


def test_external_image_with_local_service_basename_is_not_dependency(
    tmp_path: Path,
) -> None:
    tracked = make_repo(
        tmp_path,
        {
            "services/base/service.yaml": "name: base\n",
            "services/base/Dockerfile": "FROM ubuntu:24.04\n",
            "services/app/service.yaml": "name: app\n",
            "services/app/Dockerfile": "FROM example.com/base:latest\n",
        },
    )
    graph = ServiceGraph(tmp_path, tracked)
    assert graph.services["app"].dependencies == set()


def test_recipe_test_harness_changes_dirty_associated_recipe_tests(
    tmp_path: Path,
) -> None:
    tracked = make_repo(
        tmp_path,
        {
            "services/app/service.yaml": "name: app\n",
            "services/app/Dockerfile": "FROM ubuntu:24.04\n",
            "recipes/linux/one.sh": "#!/bin/sh\n",
            "recipes/linux/two.sh": "#!/bin/sh\n",
        },
    )
    graph = ServiceGraph(tmp_path, tracked)
    plan = graph.plan(["services/test-recipes/Dockerfile-one"])
    assert plan["recipes"] == ["one.sh"]

    graph = ServiceGraph(tmp_path, tracked)
    plan = graph.plan(["services/test-recipes/launch.sh"])
    assert plan["recipes"] == ["one.sh", "two.sh"]


@pytest.mark.parametrize(
    ("dependency", "error"), [("missing", "missing"), ("b", "cycle")]
)
def test_unknown_dependencies_and_cycles_fail_validation(
    tmp_path: Path, dependency: str, error: str
) -> None:
    tracked = make_repo(
        tmp_path,
        {
            "services/a/service.yaml": f"name: a\nforce_deps: [{dependency}]\n",
            "services/a/Dockerfile": "FROM ubuntu:24.04\n",
            "services/b/service.yaml": "name: b\nforce_deps: [a]\n",
            "services/b/Dockerfile": "FROM ubuntu:24.04\n",
        },
    )
    with pytest.raises(GraphError, match=error):
        ServiceGraph(tmp_path, tracked)
