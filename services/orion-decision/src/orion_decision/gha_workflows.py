# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Generate the checked-in GitHub Actions dependency workflow."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from yaml import safe_dump

from .gha_plan import job_id
from .git import GitRepo
from .orion import Service, Services, ServiceTestOnly, ToxServiceTest

WORKFLOW = Path(".github/workflows/orion.yml")
HEADER = """# GENERATED FILE — DO NOT EDIT.
# Regenerate with: python -m orion_decision.gha_workflows
# Sources: tracked service.yaml files, Dockerfiles, service inputs, and recipes.
"""


def _build_jobs(services: Services) -> dict[str, dict[str, Any]]:
    jobs: dict[str, dict[str, Any]] = {}

    def add(
        job: str,
        needs: set[str],
        kind: str,
        *,
        object_name: str,
        object_arch: str | None = None,
    ) -> None:
        if job in jobs:
            raise ValueError(f"Generated workflow job id collision: {job}")
        selected_job = f"contains(fromJSON(needs.plan.outputs.selected_jobs), '{job}')"
        prerequisite_checks = [
            "("
            f"needs.{dependency}.result == 'success' || "
            "!contains(fromJSON(needs.plan.outputs.selected_jobs), "
            f"'{dependency}'))"
            for dependency in sorted(needs)
        ]
        condition = " && ".join(
            ["always()", "!cancelled()", selected_job, *prerequisite_checks]
        )
        arch = object_arch
        name = object_name
        if kind == "build":
            assert arch is not None
        jobs[job] = {
            "name": f"{kind}: {name.replace('_', ' ')}",
            "needs": ["plan", *sorted(needs)],
            "if": condition,
            "uses": "./.github/workflows/build-service.yml",
            "with": {
                "operation": kind.replace("_", "-"),
                "name": name,
                "arch": arch or "",
                "revision": "${{ github.sha }}",
                "plan_json": "${{ needs.plan.outputs.plan_json }}",
            },
        }

    build_ids: dict[tuple[str, str], str] = {}
    for service in sorted(services.values(), key=lambda item: item.name):
        if isinstance(service, ServiceTestOnly):
            continue
        for arch in service.archs:
            build_ids[(service.name, arch)] = job_id("build", service.name, arch)

    def dependency_job_ids(service: Service, arch: str) -> set[str]:
        needed: set[str] = set()
        for dep_name in service.service_deps:
            dependency = services[dep_name]
            if isinstance(dependency, ServiceTestOnly):
                needed.add(job_id("service_test", dependency.name))
            else:
                dependency_arch = (
                    arch
                    if arch in dependency.archs
                    else "amd64"
                    if "amd64" in dependency.archs
                    else dependency.archs[0]
                )
                needed.add(build_ids[(dependency.name, dependency_arch)])
        for recipe_name in service.recipe_deps:
            needed.add(job_id("recipe_test", recipe_name))
        return needed

    def image_job_ids(image_name: str) -> set[str]:
        image = services[image_name]
        if isinstance(image, ServiceTestOnly):
            return {job_id("service_test", image.name)}
        arch = "amd64" if "amd64" in image.archs else image.archs[0]
        return {build_ids[(image.name, arch)]}

    for recipe in sorted(services.recipes.values(), key=lambda item: item.name):
        needed: set[str] = set()
        for dep_name in recipe.service_deps:
            needed.update(image_job_ids(dep_name))
        needed.update(job_id("recipe_test", name) for name in recipe.recipe_deps)
        add(
            job_id("recipe_test", recipe.name),
            needed,
            "recipe_test",
            object_name=recipe.name,
        )

    for service in sorted(services.values(), key=lambda item: item.name):
        if service.tests or isinstance(service, ServiceTestOnly):
            # A dirty CI test image is built before tests that consume it. Weak
            # dependency edges continue to avoid the bootstrap cycle.
            needed = set()
            for test in service.tests:
                if isinstance(test, ToxServiceTest) and test.image in services:
                    needed.update(image_job_ids(test.image))
            # The repository lint service spans the full graph; making it depend on
            # every recipe would create a global build gate and duplicate its result
            # gating role. Other test-only services retain their declared edges.
            if service.name != "orion":
                needed.update(dependency_job_ids(service, "amd64"))
            add(
                job_id("service_test", service.name),
                needed,
                "service_test",
                object_name=service.name,
            )
        if isinstance(service, ServiceTestOnly):
            continue
        for arch in sorted(service.archs):
            needed = dependency_job_ids(service, arch)
            if service.tests:
                needed.add(job_id("service_test", service.name))
            add(
                job_id("build", service.name, arch),
                needed,
                "build",
                object_name=service.name,
                object_arch=arch,
            )

    graph_job_ids = sorted(jobs)
    jobs["result"] = {
        "name": "Orion workflow result",
        "needs": ["plan", *graph_job_ids],
        "if": "always()",
        "runs-on": "ubuntu-latest",
        "steps": [
            {
                "name": "Check selected jobs",
                "run": (
                    "python - <<'PY'\n"
                    "import json, os, sys\n"
                    "selected = json.loads(os.environ['ORION_SELECTED_JOBS'])\n"
                    "needs = json.loads(os.environ['ORION_JOB_RESULTS'])\n"
                    "results = {\n"
                    "    name: item['result'] for name, item in needs.items()\n"
                    "}\n"
                    "failed = [\n"
                    "    job for job in selected if results.get(job) != 'success'\n"
                    "]\n"
                    "if failed:\n"
                    "    print('Selected jobs did not succeed:', ', '.join(failed))\n"
                    "    sys.exit(1)\n"
                    "PY"
                ),
                "env": {
                    "ORION_SELECTED_JOBS": "${{ needs.plan.outputs.selected_jobs }}",
                    "ORION_JOB_RESULTS": "${{ toJSON(needs) }}",
                },
            }
        ],
    }
    return jobs


def render_workflow(services: Services) -> str:
    """Render a stable workflow with a fixed job for each graph operation."""
    jobs = _build_jobs(services)
    workflow: dict[str, Any] = {
        "name": "Orion",
        "on": {
            "workflow_dispatch": {
                "inputs": {
                    "force_services": {
                        "description": "Comma-separated service names to rebuild",
                        "required": False,
                        "type": "string",
                    },
                }
            }
        },
        "permissions": {"contents": "read"},
        "jobs": {
            "plan": {
                "name": "Plan Orion graph",
                "runs-on": "ubuntu-latest",
                "outputs": {
                    "selected_jobs": "${{ steps.plan.outputs.selected_jobs }}",
                    "plan_json": "${{ steps.plan.outputs.plan_json }}",
                },
                "steps": [
                    {
                        "uses": "actions/checkout@v5",
                        "with": {"ref": "${{ github.sha }}", "fetch-depth": 0},
                    },
                    {
                        "uses": "actions/setup-python@v6",
                        "with": {"python-version": "3.13"},
                    },
                    {
                        "run": "python -m pip install -e services/orion-decision",
                    },
                    {
                        "id": "plan",
                        "env": {
                            "ORION_FORCE_SERVICES": "${{ inputs.force_services }}",
                        },
                        "run": (
                            "plan=$(python -m orion_decision.gha_plan --repo . "
                            "--revision '${{ github.sha }}' "
                            "--event '${{ github.event_name }}' "
                            "--branch '${{ github.ref_name }}' "
                            "--base-revision '${{ vars.ORION_BASE_REVISION }}' "
                            '--force-services "$ORION_FORCE_SERVICES")\n'
                            'echo "plan_json=$plan" >> "$GITHUB_OUTPUT"\n'
                            'selected=$(python -c "import json,sys; '
                            "print(json.dumps(json.load(sys.stdin)['selected_jobs'], "
                            "separators=(',', ':')))\" <<< \"$plan\")\n"
                            'echo "selected_jobs=$selected" >> "$GITHUB_OUTPUT"'
                        ),
                    },
                ],
            },
            **jobs,
        },
    }
    return HEADER + safe_dump(workflow, sort_keys=False, allow_unicode=True)


def generate(repo_path: Path, output: Path, check: bool = False) -> bool:
    """Write generated output, or report whether it is current in check mode."""
    repo = GitRepo.from_existing(repo_path)
    current = render_workflow(Services(repo))
    target = repo_path / output
    if check:
        if not target.is_file() or target.read_text() != current:
            print(f"{output} is stale; run python -m orion_decision.gha_workflows")
            return False
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(current)
    return True


def main() -> None:
    """Regenerate the workflow or check that committed output is current."""
    parser = argparse.ArgumentParser(prog="python -m orion_decision.gha_workflows")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=WORKFLOW)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not generate(args.repo, args.output, args.check):
        sys.exit(1)


if __name__ == "__main__":
    main()
