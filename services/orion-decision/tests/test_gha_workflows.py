# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Focused tests for generated GHA dependency wiring."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
from yaml import safe_load

from orion_decision.gha_plan import job_id
from orion_decision.gha_workflows import render_workflow
from orion_decision.git import GitRepo
from orion_decision.orion import Services


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def workflow_repo(root: Path, *, native: bool = False) -> Path:
    root.mkdir()
    git(root, "init", "-b", "master")
    git(root, "config", "user.name", "Orion tests")
    git(root, "config", "user.email", "orion-tests@example.invalid")
    files = {
        "services/base/service.yaml": "name: base\ntests: []\n",
        "services/base/Dockerfile": "FROM alpine:3.20\n",
        "services/weak/service.yaml": "name: weak\nforce_dirty: [base]\ntests: []\n",
        "services/weak/Dockerfile": "FROM alpine:3.20\n",
        "services/consumer/service.yaml": (
            (
                "name: consumer\n"
                "force_deps: [virtual]\n"
                "tests:\n"
                + "".join(
                    f"  - name: py{version.replace('.', '')}\n"
                    "    type: tox\n"
                    "    python: '" + version + "'\n"
                    "    toxenv: py\n"
                    for version in ("3.10", "3.11", "3.12", "3.13")
                )
            )
            if native
            else (
                "name: consumer\n"
                "force_deps: [virtual]\n"
                "tests:\n"
                "  - name: unit\n"
                "    type: tox\n"
                "    image: base\n"
                "    toxenv: py\n"
            )
        ),
        "services/consumer/Dockerfile": (
            "FROM mozillasecurity/base:latest\nRUN recipes/rebuild.sh\n"
        ),
        "services/virtual/service.yaml": "name: virtual\ntype: test\n",
        "services/orion/service.yaml": (
            "name: orion\n"
            "type: test\n"
            "tests:\n"
            "  - name: lint\n"
            "    type: tox\n"
            "    image: base\n"
            "    toxenv: lint\n"
        ),
        "recipes/rebuild.sh": "#!/bin/sh\n# /force-dirty=base\necho rebuild\n",
    }
    for name, contents in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    git(root, "add", "-A")
    git(root, "commit", "-m", "workflow graph")
    return root


def jobs_for(repo: Path) -> dict[str, dict[str, Any]]:
    rendered = render_workflow(Services(GitRepo.from_existing(repo)))
    return safe_load(rendered.split("\n", 3)[3])["jobs"]


def evaluate_job_condition(
    condition: str, selected_jobs: set[str], results: dict[str, str]
) -> bool:
    """Evaluate the generated workflow's small job-condition expression subset."""
    expression = condition.replace("always()", "True").replace("!cancelled()", "True")

    def selected_match(match: re.Match[str]) -> str:
        selected = match.group(2) in selected_jobs
        return str(not selected if match.group(1) else selected)

    expression = re.sub(
        r"(!?)contains\(fromJSON\(needs\.plan\.outputs\.selected_jobs\), "
        r"'([^']+)'\)",
        selected_match,
        expression,
    )
    expression = re.sub(
        r"needs\.([a-zA-Z0-9_-]+)\.result == 'success'",
        lambda match: str(results.get(match.group(1)) == "success"),
        expression,
    )
    expression = expression.replace("&&", " and ").replace("||", " or ")
    return bool(eval(expression, {"__builtins__": {}}, {}))


def test_workflow_is_independent_of_service_and_recipe_insertion_order(
    tmp_path: Path,
) -> None:
    """Rendering is stable regardless of graph insertion order."""
    repo = workflow_repo(tmp_path / "repo")
    services = Services(GitRepo.from_existing(repo))
    expected = render_workflow(services)
    reverse_services = list(services.items())[::-1]
    reverse_recipes = list(services.recipes.items())[::-1]
    services.clear()
    services.update(reverse_services)
    services.recipes = dict(reverse_recipes)

    assert render_workflow(services) == expected


def test_needs_include_hard_and_test_image_edges_but_exclude_weak_edges(
    tmp_path: Path,
) -> None:
    """Generated dependencies include hard and test-image edges but omit weak edges."""
    jobs = jobs_for(workflow_repo(tmp_path / "repo"))
    consumer_needs = jobs[job_id("build", "consumer", "amd64")]["needs"]
    weak_needs = jobs[job_id("build", "weak", "amd64")]["needs"]
    recipe_needs = jobs[job_id("recipe_test", "rebuild.sh")]["needs"]

    assert job_id("build", "base", "amd64") in consumer_needs
    assert job_id("service_test", "virtual") in consumer_needs
    assert (
        job_id("build", "base", "amd64")
        in jobs[job_id("service_test", "consumer")]["needs"]
    )
    assert (
        job_id("service_test", "virtual")
        in jobs[job_id("service_test", "consumer")]["needs"]
    )
    assert (
        job_id("recipe_test", "rebuild.sh")
        in jobs[job_id("service_test", "consumer")]["needs"]
    )
    assert (
        job_id("build", "base", "amd64")
        in jobs[job_id("service_test", "orion")]["needs"]
    )
    assert job_id("build", "base", "amd64") not in weak_needs
    assert job_id("build", "base", "amd64") not in recipe_needs


def test_native_tests_generate_python_matrix_and_keep_service_gate_edges(
    tmp_path: Path,
) -> None:
    """Native matrix rows retain graph selection and build consumer gating."""
    repo = workflow_repo(tmp_path / "repo", native=True)
    jobs = jobs_for(repo)
    test_id = job_id("service_test", "consumer")
    test_job = jobs[test_id]
    build_id = job_id("build", "consumer", "amd64")

    assert test_job["needs"] == [
        "plan",
        job_id("build", "base", "amd64"),
        job_id("recipe_test", "rebuild.sh"),
        job_id("service_test", "virtual"),
    ]
    rows = json.loads(test_job["with"]["tests_json"])
    assert rows == [
        {
            "name": f"py{version.replace('.', '')}",
            "python": version,
            "test_index": index,
        }
        for index, version in enumerate(("3.10", "3.11", "3.12", "3.13"))
    ]
    # Builds that consume this service's outputs remain gated by this same job id.
    assert test_id in jobs[build_id]["needs"]
    assert job_id("build", "base", "amd64") in test_job["needs"]
    assert test_id in jobs["graph-result"]["needs"]
    condition = test_job["if"]
    dependency = job_id("service_test", "virtual")
    assert evaluate_job_condition(
        condition, {test_id, dependency}, {dependency: "success"}
    )
    assert not evaluate_job_condition(condition, {dependency}, {dependency: "success"})
    assert not evaluate_job_condition(
        condition, {test_id, dependency}, {dependency: "failure"}
    )
    assert evaluate_job_condition(condition, {test_id}, {dependency: "skipped"})

    build_condition = jobs[build_id]["if"]
    assert evaluate_job_condition(
        build_condition, {build_id, test_id}, {test_id: "success"}
    )
    assert not evaluate_job_condition(
        build_condition, {build_id, test_id}, {test_id: "failure"}
    )


def test_native_test_metadata_cannot_be_mixed_with_image_tests(tmp_path: Path) -> None:
    """A partial native matrix is rejected instead of silently omitting tests."""
    repo = workflow_repo(tmp_path / "repo", native=True)
    metadata = repo / "services/consumer/service.yaml"
    metadata.write_text(
        metadata.read_text()
        + "  - name: image-test\n"
        + "    type: tox\n"
        + "    image: base\n"
        + "    toxenv: py\n"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "mixed test modes")

    with pytest.raises(ValueError, match="mixes native Python and image-based"):
        render_workflow(Services(GitRepo.from_existing(repo)))


def test_root_lint_is_in_acyclic_graph_and_remains_an_aggregate_job(
    tmp_path: Path,
) -> None:
    """The root lint job stays acyclic and participates in aggregate results."""
    jobs = jobs_for(workflow_repo(tmp_path / "repo"))
    dependencies = {
        name: [need for need in job.get("needs", []) if need != "plan"]
        for name, job in jobs.items()
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise AssertionError(f"workflow dependency cycle through {name}")
        if name in visited:
            return
        visiting.add(name)
        for dep in dependencies[name]:
            assert dep in jobs
            visit(dep)
        visiting.remove(name)
        visited.add(name)

    for name in jobs:
        visit(name)

    assert job_id("service_test", "orion") in jobs
    assert job_id("service_test", "orion") in jobs["graph-result"]["needs"]
    assert "graph-result" in jobs["result"]["needs"]


def test_duplicate_sanitized_job_ids_are_rejected(tmp_path: Path) -> None:
    """Names that sanitize to the same generated job ID are rejected."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "master")
    git(repo, "config", "user.name", "Orion tests")
    git(repo, "config", "user.email", "orion-tests@example.invalid")
    for name in ("foo-bar", "foo_bar"):
        folder = repo / "services" / name
        folder.mkdir(parents=True)
        (folder / "service.yaml").write_text(f"name: {name}\ntests: []\n")
        (folder / "Dockerfile").write_text("FROM alpine:3.20\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "colliding names")

    with pytest.raises(ValueError, match="job id"):
        render_workflow(Services(GitRepo.from_existing(repo)))
