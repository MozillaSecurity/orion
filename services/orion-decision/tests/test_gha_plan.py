# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Focused integration tests for GHA graph planning."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from orion_decision import gha_publish
from orion_decision.gha_plan import build_plan, job_id


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def make_repo(root: Path) -> Path:
    """Create a small tracked graph with hard, weak, recipe and test-image edges."""
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
            "name: consumer\n"
            "tests:\n"
            "  - name: unit\n"
            "    type: tox\n"
            "    image: base\n"
            "    toxenv: py\n"
        ),
        "services/consumer/Dockerfile": (
            "FROM mozillasecurity/base:latest\n"
            "COPY shared/input.txt /shared.txt\n"
            "RUN recipes/install.sh\n"
        ),
        "services/virtual/service.yaml": "name: virtual\ntype: test\n",
        "services/virtual/tests/test_graph.py": "def test_virtual(): pass\n",
        "shared/input.txt": "shared input\n",
        "recipes/install.sh": "#!/bin/sh\n# /force-dirty=base\necho install\n",
        "recipes/tests/helper.sh": "#!/bin/sh\necho test fixture\n",
        "README.md": "initial\n",
    }
    for name, contents in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    commit(root, "initial graph")
    return root


def test_deleted_external_input_uses_baseline_graph(tmp_path: Path) -> None:
    """A deleted shared input still selects its former dependent service."""
    repo = make_repo(tmp_path / "repo")
    baseline = git(repo, "rev-parse", "HEAD")
    (repo / "shared/input.txt").unlink()
    revision = commit(repo, "remove shared input")

    plan = build_plan(
        repo,
        revision=revision,
        event="pull_request",
        branch="feature",
        base_revision=baseline,
    )

    assert "shared/input.txt" in plan["changed_paths"]
    assert "consumer" in plan["services"]
    assert job_id("build", "consumer", "amd64") in plan["selected_jobs"]


def test_pr_deleted_input_uses_merge_base_graph_after_target_removes_reference(
    tmp_path: Path,
) -> None:
    """A PR deletion is attributed using the merge-base dependency graph."""
    repo = make_repo(tmp_path / "repo")
    common = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-b", "target", common)
    dockerfile = repo / "services/consumer/Dockerfile"
    dockerfile.write_text("FROM mozillasecurity/base:latest\nRUN recipes/install.sh\n")
    target_revision = commit(repo, "target removes shared input reference")

    git(repo, "checkout", "-b", "feature", common)
    (repo / "shared/input.txt").unlink()
    revision = commit(repo, "PR removes shared input")

    plan = build_plan(
        repo,
        revision=revision,
        event="pull_request",
        branch="feature",
        base_revision=target_revision,
    )

    assert "shared/input.txt" in plan["changed_paths"]
    assert "consumer" in plan["services"]


def test_renamed_external_input_selects_old_dependency_owner(tmp_path: Path) -> None:
    """A rename selects dependents of both the old and new paths."""
    repo = make_repo(tmp_path / "repo")
    baseline = git(repo, "rev-parse", "HEAD")
    git(repo, "mv", "shared/input.txt", "shared/renamed.txt")
    revision = commit(repo, "rename shared input")

    plan = build_plan(
        repo,
        revision=revision,
        event="pull_request",
        branch="feature",
        base_revision=baseline,
    )

    assert "shared/input.txt" in plan["changed_paths"]
    assert "shared/renamed.txt" in plan["changed_paths"]
    assert "consumer" in plan["services"]


def test_test_only_file_edit_selects_owning_service_test(tmp_path: Path) -> None:
    """A service test edit selects only that service's test job."""
    repo = make_repo(tmp_path / "repo")
    baseline = git(repo, "rev-parse", "HEAD")
    test_file = repo / "services/virtual/tests/test_graph.py"
    test_file.write_text("def test_virtual(): assert True\n")
    revision = commit(repo, "edit virtual service tests")

    plan = build_plan(
        repo,
        revision=revision,
        event="pull_request",
        branch="feature",
        base_revision=baseline,
    )

    assert plan["services"] == ["virtual"]
    assert plan["selected_jobs"] == [job_id("service_test", "virtual")]


def test_recipe_edit_does_not_select_sibling_or_test_fixture_recipes(
    tmp_path: Path,
) -> None:
    """A recipe edit selects it without selecting sibling or fixture recipes."""
    repo = make_repo(tmp_path / "repo")
    (repo / "recipes/other.sh").write_text("#!/bin/sh\necho other\n")
    baseline = commit(repo, "add independent recipe")
    (repo / "recipes/other.sh").write_text("#!/bin/sh\necho changed\n")
    revision = commit(repo, "change independent recipe")

    plan = build_plan(
        repo,
        revision=revision,
        event="pull_request",
        branch="feature",
        base_revision=baseline,
    )

    assert plan["recipes"] == ["other.sh"]
    assert "helper.sh" not in plan["recipes"]
    assert "install.sh" not in plan["recipes"]


def test_forced_service_rebuild_propagates_through_weak_and_recipe_edges(
    tmp_path: Path,
) -> None:
    """A forced rebuild propagates through weak and recipe dependencies."""
    repo = make_repo(tmp_path / "repo")
    revision = git(repo, "rev-parse", "HEAD")

    plan = build_plan(
        repo,
        revision=revision,
        event="workflow_dispatch",
        branch="feature",
        base_revision=revision,
        force_services=["base"],
    )

    assert {"base", "consumer", "weak"} <= set(plan["services"])
    assert "install.sh" in plan["recipes"]
    assert job_id("build", "weak", "amd64") in plan["selected_jobs"]
    assert job_id("recipe_test", "install.sh") in plan["selected_jobs"]


def test_commit_directive_is_read_from_entire_range(tmp_path: Path) -> None:
    """A force directive in any commit in the range selects its service."""
    repo = make_repo(tmp_path / "repo")
    baseline = git(repo, "rev-parse", "HEAD")
    (repo / "README.md").write_text("first\n")
    commit(repo, "first change\n\n/force-rebuild=weak")
    (repo / "README.md").write_text("second\n")
    revision = commit(repo, "follow-up without directive")

    plan = build_plan(
        repo,
        revision=revision,
        event="push",
        branch="master",
        base_revision=baseline,
    )

    assert plan["services"] == ["weak"]
    assert plan["reasons"]["service:weak"] == ["manual-force"]


def test_pull_request_and_push_use_their_expected_diff_ranges(tmp_path: Path) -> None:
    """Pull requests and pushes compare changes against their expected ranges."""
    repo = make_repo(tmp_path / "repo")
    common = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-b", "master-next")
    alpha = repo / "services/base/Dockerfile"
    alpha.write_text("FROM alpine:3.21\n")
    base_revision = commit(repo, "change only base")
    git(repo, "checkout", "-b", "feature", common)
    beta = repo / "services/weak/Dockerfile"
    beta.write_text("FROM alpine:3.21\n")
    revision = commit(repo, "change only weak")

    pr = build_plan(
        repo,
        revision=revision,
        event="pull_request",
        branch="feature",
        base_revision=base_revision,
    )
    push = build_plan(
        repo,
        revision=revision,
        event="push",
        branch="feature",
        base_revision=base_revision,
    )

    assert "services/weak/Dockerfile" in pr["changed_paths"]
    assert "services/base/Dockerfile" not in pr["changed_paths"]
    assert "services/base/Dockerfile" in push["changed_paths"]
    assert "services/weak/Dockerfile" in push["changed_paths"]


def test_requested_revision_must_match_checked_out_head(tmp_path: Path) -> None:
    """Planning rejects a revision that differs from the checked-out HEAD."""
    repo = make_repo(tmp_path / "repo")
    revision = git(repo, "rev-parse", "HEAD")

    with pytest.raises(ValueError, match="does not match checkout"):
        build_plan(
            repo,
            revision="0" * 40,
            event="push",
            branch="master",
            base_revision=revision,
        )


@pytest.mark.parametrize(
    ("event", "branch", "expected"),
    [
        ("push", "feature", False),
        ("pull_request", "master", False),
        ("push", "master", True),
    ],
)
def test_publication_is_limited_to_main_pushes(
    tmp_path: Path, event: str, branch: str, expected: bool
) -> None:
    """Publication is enabled only for pushes to the main branch."""
    repo = make_repo(tmp_path / "repo")
    revision = git(repo, "rev-parse", "HEAD")

    plan = build_plan(
        repo,
        revision=revision,
        event=event,
        branch=branch,
        base_revision=revision,
    )

    assert plan["publish"] is expected


def test_main_schedule_expiry_ignores_virtual_services(tmp_path: Path) -> None:
    """Scheduled expiry selects expired buildable services and ignores virtual ones."""
    repo = make_repo(tmp_path / "repo")
    revision = git(repo, "rev-parse", "HEAD")

    plan = build_plan(
        repo,
        revision=revision,
        event="schedule",
        branch="master",
        base_revision=revision,
        expired_services=["base", "virtual"],
    )

    assert "base" in plan["services"]
    assert "virtual" not in plan["services"]
    assert job_id("service_test", "virtual") not in plan["selected_jobs"]
    assert plan["publish"] is True


def test_missing_baseline_selects_full_graph_including_recipes(tmp_path: Path) -> None:
    """A missing baseline triggers a full service and recipe rebuild."""
    repo = make_repo(tmp_path / "repo")
    revision = git(repo, "rev-parse", "HEAD")

    plan = build_plan(
        repo, revision=revision, event="push", branch="master", base_revision=None
    )

    assert set(plan["services"]) == {"base", "consumer", "virtual", "weak"}
    assert plan["recipes"] == ["install.sh"]
    assert job_id("recipe_test", "install.sh") in plan["selected_jobs"]
    assert plan["full_rebuild_reason"] == "baseline-missing"


def test_peer_fix_uses_each_services_last_published_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A peer fix rebuilds only the service that failed the earlier publication."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "master")
    git(repo, "config", "user.name", "Orion tests")
    git(repo, "config", "user.email", "orion-tests@example.invalid")
    for name in ("x", "y", "z"):
        service = repo / "services" / name
        service.mkdir(parents=True)
        (service / "service.yaml").write_text(f"name: {name}\ntests: []\n")
        (service / "Dockerfile").write_text("FROM alpine:3.20\n")
    base_revision = commit(repo, "initial services")

    for name in ("x", "y", "z"):
        (repo / "services" / name / "Dockerfile").write_text("FROM alpine:3.21\n")
    published_revision = commit(repo, "update all services")

    (repo / "services/z/Dockerfile").write_text("FROM alpine:3.22\n")
    revision = commit(repo, "fix z")
    monkeypatch.setattr(
        gha_publish,
        "publication_state",
        lambda: {
            "base_revision": base_revision,
            "expired_services": [],
            "service_revisions": {
                "x": published_revision,
                "y": published_revision,
                "z": base_revision,
            },
        },
    )

    plan = build_plan(
        repo,
        revision=revision,
        event="push",
        branch="master",
        baseline_from_taskcluster=True,
    )

    assert plan["services"] == ["z"]
    assert plan["selected_jobs"] == [job_id("build", "z", "amd64")]


def test_per_service_baseline_propagates_nested_recipe_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A nested recipe edit rebuilds outer recipes and each dependent service."""
    repo = make_repo(tmp_path / "repo")
    consumer = repo / "services/consumer/Dockerfile"
    consumer.write_text("FROM mozillasecurity/base:latest\nRUN recipes/outer.sh\n")
    (repo / "recipes/outer.sh").write_text("#!/bin/sh\nrecipes/inner.sh\n")
    (repo / "recipes/inner.sh").write_text("#!/bin/sh\necho old\n")
    baseline = commit(repo, "add nested recipes")
    (repo / "recipes/inner.sh").write_text("#!/bin/sh\necho fixed\n")
    revision = commit(repo, "fix nested recipe")
    monkeypatch.setattr(
        gha_publish,
        "publication_state",
        lambda: {
            "base_revision": baseline,
            "expired_services": [],
            "service_revisions": {"consumer": baseline},
        },
    )

    plan = build_plan(
        repo,
        revision=revision,
        event="push",
        branch="master",
        baseline_from_taskcluster=True,
    )

    assert "consumer" in plan["services"]
    assert {"inner.sh", "outer.sh"} <= set(plan["recipes"])
    assert job_id("build", "consumer", "amd64") in plan["selected_jobs"]


def test_per_service_baseline_selects_new_test_only_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A newly added test-only service is selected without an old graph node."""
    repo = make_repo(tmp_path / "repo")
    baseline = git(repo, "rev-parse", "HEAD")
    new_service = repo / "services/new-test"
    new_service.mkdir()
    (new_service / "service.yaml").write_text("name: new-test\ntype: test\n")
    (new_service / "tests").mkdir()
    (new_service / "tests/test_new.py").write_text("def test_new(): pass\n")
    revision = commit(repo, "add test-only service")
    monkeypatch.setattr(
        gha_publish,
        "publication_state",
        lambda: {
            "base_revision": baseline,
            "expired_services": [],
            "service_revisions": {"consumer": baseline},
        },
    )

    plan = build_plan(
        repo,
        revision=revision,
        event="push",
        branch="master",
        baseline_from_taskcluster=True,
    )

    assert "new-test" in plan["services"]
    assert job_id("service_test", "new-test") in plan["selected_jobs"]


def test_newer_same_revision_dependency_retries_weak_dependent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed weak dependent retries after its parent refreshes at the same SHA."""
    repo = make_repo(tmp_path / "repo")
    baseline = git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(
        gha_publish,
        "publication_state",
        lambda: {
            "base_revision": baseline,
            "expired_services": [],
            "service_revisions": {"base": baseline, "weak": baseline},
            "service_runs": {"base": (20, 1), "weak": (10, 1)},
        },
    )

    plan = build_plan(
        repo,
        revision=baseline,
        event="push",
        branch="master",
        baseline_from_taskcluster=True,
    )

    assert "weak" in plan["services"]
    assert job_id("build", "weak", "amd64") in plan["selected_jobs"]
