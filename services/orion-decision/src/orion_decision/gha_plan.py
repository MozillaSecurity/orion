# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Plan the statically generated GitHub Actions service graph."""

from __future__ import annotations

import json
import re
import subprocess
import tarfile
from argparse import ArgumentParser
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .git import GitRepo
from .orion import ServiceHomebrew, ServiceMsys, Services, ServiceTestOnly


class _SnapshotRepo(GitRepo):
    """Minimal repository interface over a temporary git archive."""

    __slots__ = ("_files",)

    def __init__(self, path: Path, files: list[str]) -> None:
        self._cloned = False
        self.path = path
        self._files = files

    def git(self, *args: Path | str, **_kwargs: Any) -> str:
        if args[:2] == ("ls-files", "--"):
            return "\n".join(self._files)
        raise ValueError(f"Unsupported snapshot git command: {args!r}")


def _load_snapshot(repo: GitRepo, revision: str) -> tuple[Services, TemporaryDirectory]:
    """Build a previous service graph from tracked files at a base revision."""
    assert repo.path is not None
    files = repo.git("ls-tree", "-r", "--name-only", "-z", revision).split("\0")
    files = [path for path in files if path]
    tar_data = subprocess.run(
        ["git", "archive", revision],
        cwd=repo.path,
        check=True,
        capture_output=True,
    ).stdout
    temp_dir = TemporaryDirectory(prefix="orion-graph-base-")
    root = Path(temp_dir.name)
    with tarfile.open(fileobj=BytesIO(tar_data)) as archive:
        archive.extractall(root)
    return Services(_SnapshotRepo(root, files)), temp_dir


def job_id(kind: str, name: str, arch: str | None = None) -> str:
    """Return the stable job id used by both the workflow and planner."""
    safe_name = "".join(char if char.isalnum() or char == "_" else "_" for char in name)
    return f"{kind}_{safe_name}" + (f"_{arch}" if arch else "")


def selected_job_ids(services: Services) -> set[str]:
    """Return graph job ids selected by dirty service and recipe state."""
    selected: set[str] = {
        job_id("recipe_test", recipe.name)
        for recipe in services.recipes.values()
        if recipe.dirty
    }
    for service in services.values():
        if not service.dirty:
            continue
        if service.tests or isinstance(service, ServiceTestOnly):
            selected.add(job_id("service_test", service.name))
        if isinstance(service, ServiceTestOnly):
            continue
        for arch in service.archs:
            selected.add(job_id("build", service.name, arch))
    return selected


def plan_selection(
    services: Services,
    *,
    changed_paths: list[Path] | None = None,
    previous_services: Services | None = None,
    force_services: list[str] | None = None,
    expired_services: list[str] | None = None,
    mark_changes: bool = True,
) -> dict[str, Any]:
    """Apply changed, forced, and expiry selections and return plan metadata."""
    changed_paths = changed_paths or []
    force_services = force_services or []
    expired_services = [
        name
        for name in expired_services or []
        if name in services and not isinstance(services[name], ServiceTestOnly)
    ]
    if mark_changes:
        services.mark_changed_dirty(changed_paths, previous_services)
    services.force_dirty(force_services)
    services.force_dirty(expired_services)
    dirty_services = sorted(name for name, service in services.items() if service.dirty)
    dirty_recipes = sorted(
        name for name, recipe in services.recipes.items() if recipe.dirty
    )
    reasons: dict[str, list[str]] = {}
    root = services.root
    changed = {
        (path if path.is_absolute() else (root / path if root else path)).as_posix()
        for path in changed_paths
    }
    forced = set(force_services)
    expired = set(expired_services)
    for name in dirty_services:
        service = services[name]
        service_reasons: list[str] = []
        if name in forced:
            service_reasons.append("manual-force")
        if name in expired:
            service_reasons.append("expiry")
        if any(path.as_posix() in changed for path in service.path_deps):
            service_reasons.append("changed-path")
        if not service_reasons:
            service_reasons.append("dependency")
        reasons[f"service:{name}"] = service_reasons
    for name in dirty_recipes:
        recipe = services.recipes[name]
        reasons[f"recipe:{name}"] = (
            ["changed-path"]
            if any(path.as_posix() in changed for path in recipe.path_deps)
            else ["dependency"]
        )
    return {
        "services": dirty_services,
        "recipes": dirty_recipes,
        "selected_jobs": sorted(selected_job_ids(services)),
        "selected_docker_jobs": sorted(
            job_id("build", service.name, arch)
            for service in services.values()
            if service.dirty
            and not isinstance(service, (ServiceTestOnly, ServiceMsys, ServiceHomebrew))
            for arch in service.archs
        ),
        "reasons": reasons,
    }


def _mark_published_changes_dirty(
    services: Services,
    repo: GitRepo,
    *,
    revision: str,
    baseline_revision: str | None,
    service_revisions: dict[str, str],
    service_runs: dict[str, tuple[int, int]],
    changed_paths: list[Path],
    previous_services: Services | None,
) -> None:
    """Select changes since each service's own last indexed artifact revision."""
    assert services.root is not None
    repo_path = repo.path
    assert repo_path is not None
    snapshots: dict[str, tuple[Services, TemporaryDirectory[str]]] = {}

    def snapshot(base: str) -> Services:
        if base not in snapshots:
            snapshots[base] = _load_snapshot(repo, base)
        return snapshots[base][0]

    try:
        # Recipe tests use the complete-publication baseline. Per-service baselines
        # below keep already-published services from being rebuilt after a peer fix.
        if previous_services is not None and previous_services.root is not None:
            recipe_graph = Services(GitRepo.from_existing(repo_path))
            recipe_graph.mark_changed_dirty(changed_paths, previous_services)
            for name, recipe in recipe_graph.recipes.items():
                if recipe.dirty and name in services.recipes:
                    services.recipes[name].dirty = True

        dirty_services = []
        for service in services.values():
            base = service_revisions.get(service.name, baseline_revision)
            if base is None:
                service.dirty = True
                dirty_services.append(service)
                continue
            paths = set(_diff_paths(repo, base, revision, event_is_pull_request=False))
            old_graph = snapshot(base)
            old_service = old_graph.get(service.name)
            baseline_graph = Services(GitRepo.from_existing(repo_path))
            baseline_graph.mark_changed_dirty(list(paths), old_graph)
            if baseline_graph[service.name].dirty:
                service.dirty = True
                dirty_services.append(service)

            dependency_names = set(service.service_deps | service.weak_deps)
            if old_service is not None:
                dependency_names |= old_service.service_deps | old_service.weak_deps
            recipe_names = set(service.recipe_deps)
            if old_service is not None:
                recipe_names |= old_service.recipe_deps
            pending_recipes = list(recipe_names)
            while pending_recipes:
                recipe_name = pending_recipes.pop()
                current_recipe = services.recipes.get(recipe_name)
                previous_recipe = old_graph.recipes.get(recipe_name)
                if current_recipe is not None:
                    dependency_names |= (
                        current_recipe.service_deps | current_recipe.weak_deps
                    )
                    pending_recipes.extend(current_recipe.recipe_deps - recipe_names)
                    recipe_names.add(recipe_name)
                if previous_recipe is not None:
                    dependency_names |= (
                        previous_recipe.service_deps | previous_recipe.weak_deps
                    )
                    pending_recipes.extend(previous_recipe.recipe_deps - recipe_names)
                    recipe_names.add(recipe_name)
            for dependency in dependency_names:
                dependency_revision = service_revisions.get(dependency)
                dependency_run = service_runs.get(dependency)
                service_run = service_runs.get(service.name)
                revision_is_newer = False
                if dependency_revision is not None and dependency_revision != base:
                    merge_base = repo.git(
                        "merge-base", base, dependency_revision
                    ).strip()
                    revision_is_newer = merge_base == base
                run_is_newer = (
                    dependency_run is not None
                    and service_run is not None
                    and dependency_run > service_run
                )
                if revision_is_newer or run_is_newer:
                    service.dirty = True
                    if service not in dirty_services:
                        dirty_services.append(service)
                    break

        services.propagate_dirty(dirty_services)
    finally:
        for _, temporary in snapshots.values():
            temporary.cleanup()


def _diff_paths(
    repo: GitRepo,
    base_revision: str,
    revision: str,
    *,
    event_is_pull_request: bool,
) -> list[Path]:
    """List changed paths including deletions between two exact revisions."""
    separator = "..." if event_is_pull_request else ".."
    output = repo.git(
        "diff",
        "--name-only",
        "--no-renames",
        "--diff-filter=ACDMRTUXB",
        "-z",
        f"{base_revision}{separator}{revision}",
    )
    return [Path(path) for path in output.split("\0") if path]


def build_plan(
    repo_path: Path,
    *,
    revision: str,
    event: str,
    branch: str,
    base_revision: str | None = None,
    force_services: list[str] | None = None,
    expired_services: list[str] | None = None,
    main_branch: str = "master",
    baseline_from_taskcluster: bool = False,
) -> dict[str, Any]:
    """Build a plan for the checked-out revision without mutating git state."""
    repo = GitRepo.from_existing(repo_path)
    actual_revision = repo.head()
    if actual_revision != revision:
        raise ValueError(
            f"Requested revision {revision!r} does not match "
            f"checkout {actual_revision!r}"
        )
    state: dict[str, Any] = {
        "base_revision": None,
        "expired_services": [],
        "service_revisions": {},
        "service_runs": {},
        "incomplete_services": [],
        "docker_latest_failed": [],
    }
    if baseline_from_taskcluster and event in {"push", "schedule", "workflow_dispatch"}:
        from .gha_publish import publication_state

        state = publication_state()
        base_revision = base_revision or state["base_revision"]
        expired_services = list(expired_services or []) + state["expired_services"]
    retry_services = state.get("docker_latest_failed", []) + state.get(
        "incomplete_services", []
    )
    graph = Services(repo)
    previous_graph = None
    snapshot_temp_dir = None
    changed_paths: list[Path] = []
    full_rebuild_reason = None
    baseline_usable = bool(base_revision)
    if base_revision:
        try:
            graph_base_revision = (
                repo.git("merge-base", base_revision, revision).strip()
                if event == "pull_request"
                else base_revision
            )
            changed_paths = _diff_paths(
                repo,
                base_revision,
                revision,
                event_is_pull_request=event == "pull_request",
            )
            previous_graph, snapshot_temp_dir = _load_snapshot(
                repo, graph_base_revision
            )
        except (subprocess.CalledProcessError, tarfile.TarError):
            full_rebuild_reason = "baseline-unavailable"
            baseline_usable = False
    elif event in {"push", "schedule", "workflow_dispatch"}:
        # Without a known successful publication baseline, selecting the full graph
        # is the only safe incremental plan. Step 3 supplies that baseline from TC.
        full_rebuild_reason = "baseline-missing"
    commit_message = repo.git(
        "log",
        "--format=%B",
        f"{base_revision}..{revision}" if baseline_usable else "-1",
    )
    force_all = False
    directive_forced: set[str] = set()
    for match in re.finditer(r"/force-rebuild(=[A-Za-z0-9_.,-]+)?", commit_message):
        if match.group(1):
            directive_forced.update(match.group(1)[1:].split(","))
        else:
            force_all = True
    invalid_forced = directive_forced - graph.keys()
    if invalid_forced:
        raise ValueError(
            f"/force-rebuild of unknown service(s): {sorted(invalid_forced)}"
        )
    force_services = list(force_services or []) + sorted(directive_forced)
    partial_baseline = (
        baseline_from_taskcluster
        and bool(state.get("service_revisions"))
        and full_rebuild_reason == "baseline-missing"
    )
    if force_all or (full_rebuild_reason and not partial_baseline):
        force_services = sorted(set(force_services) | set(graph))
    if full_rebuild_reason:
        # No successful publication baseline means recipe coverage is also unknown.
        for recipe in graph.recipes.values():
            recipe.dirty = True
    per_service_baselines = (
        baseline_from_taskcluster
        and event in {"push", "schedule", "workflow_dispatch"}
        and (baseline_usable or partial_baseline)
        and bool(state.get("service_revisions"))
    )
    if per_service_baselines:
        _mark_published_changes_dirty(
            graph,
            repo,
            revision=revision,
            baseline_revision=base_revision,
            service_revisions=state["service_revisions"],
            service_runs=state.get("service_runs", {}),
            changed_paths=changed_paths,
            previous_services=previous_graph,
        )
    result = plan_selection(
        graph,
        changed_paths=changed_paths,
        previous_services=None if per_service_baselines else previous_graph,
        force_services=list(force_services or []) + retry_services,
        expired_services=expired_services,
        mark_changes=not per_service_baselines,
    )
    publish = (
        event in {"push", "schedule", "workflow_dispatch"} and branch == main_branch
    )
    result.update(
        {
            "revision": revision,
            "event": event,
            "branch": branch,
            "publish": publish,
            "changed_paths": sorted(path.as_posix() for path in changed_paths),
            "full_rebuild_reason": full_rebuild_reason,
            "baseline_revision": base_revision,
            "expired_services": sorted(set(expired_services or [])),
        }
    )
    if full_rebuild_reason:
        for item_reasons in result["reasons"].values():
            item_reasons[:] = [full_rebuild_reason]
    del snapshot_temp_dir
    return result


def main() -> None:
    """Print a compact JSON plan for workflow jobs."""
    parser = ArgumentParser(prog="python -m orion_decision.gha_plan")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--revision", required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--base-revision")
    parser.add_argument("--force-service", action="append", default=[])
    parser.add_argument("--force-services", default="")
    parser.add_argument("--expired-service", action="append", default=[])
    parser.add_argument("--baseline-from-taskcluster", action="store_true")
    args = parser.parse_args()
    plan = build_plan(
        args.repo,
        revision=args.revision,
        event=args.event,
        branch=args.branch,
        base_revision=args.base_revision,
        force_services=args.force_service
        + [name for name in args.force_services.split(",") if name],
        expired_services=args.expired_service,
        baseline_from_taskcluster=args.baseline_from_taskcluster,
    )
    print(json.dumps(plan, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
