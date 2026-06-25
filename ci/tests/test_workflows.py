from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from ci.workflows import generate, render


def test_generated_workflow_gates_builds_and_uses_graph_dependencies() -> None:
    workflow = generate(Path(__file__).resolve().parents[2])
    jobs = workflow["jobs"]

    assert "build_grizzly" in jobs["build_grizzly_android"]["needs"]
    assert "test_gate" in jobs["build_grizzly_android"]["needs"]
    assert "recipe_gate" in jobs["build_grizzly_android"]["needs"]
    assert jobs["build_fuzzilli"]["strategy"]["matrix"]["arch"] == ["amd64", "arm64"]
    assert "build_symbol_filter" not in jobs
    build_jobs = {name for name in jobs if name.startswith("build_")}
    assert set(jobs["publish"]["needs"]) == build_jobs | {
        "plan",
        "test_gate",
        "recipe_gate",
    }
    assert set(jobs["complete"]["needs"]) == jobs.keys() - {"complete"}
    assert "ci_tests" in jobs["test_gate"]["needs"]
    assert "build_base_python" in jobs["build_covdiff"]["needs"]
    assert "build_base_node" in jobs["build_domino_web_tests"]["needs"]


def test_rendered_workflow_is_valid_yaml_and_deterministic() -> None:
    root = Path(__file__).resolve().parents[2]
    first = render(root)
    second = render(root)
    workflow = yaml.load(first, Loader=yaml.BaseLoader)

    assert first == second
    assert "on" in workflow
    assert "workflow_dispatch" in workflow["on"]
    assert "schedule" in workflow["on"]
    assert "complete" in workflow["jobs"]
    assert (root / ".github/workflows/orion.yml").read_text() == first


@pytest.mark.parametrize("job", ["test_gate", "recipe_gate", "complete"])
@pytest.mark.parametrize(
    ("result", "exit_code"),
    [("success", 0), ("skipped", 0), ("failure", 1), ("cancelled", 1)],
)
def test_gate_commands_propagate_job_outcomes(
    job: str, result: str, exit_code: int
) -> None:
    workflow = generate(Path(__file__).resolve().parents[2])
    step = workflow["jobs"][job]["steps"][0]
    needs = {
        "before": {"result": "success"},
        "subject": {"result": result},
        "after": {"result": "success"},
    }
    completed = subprocess.run(
        ["bash", "-c", step["run"]],
        env={**os.environ, "NEEDS": json.dumps(needs), "RESULT": result},
        capture_output=True,
        text=True,
    )
    assert completed.returncode == exit_code, completed.stderr
