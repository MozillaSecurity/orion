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
from .orion import (
    Service,
    ServiceHomebrew,
    ServiceMsys,
    Services,
    ServiceTestOnly,
    ToxServiceTest,
)

WORKFLOW = Path(".github/workflows/orion.yml")
HEAD_SHA = "${{ github.event.pull_request.head.sha || github.sha }}"
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
        runner: str = "ubuntu-24.04",
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
                "runner": runner,
                "revision": HEAD_SHA,
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
                runner=(
                    "windows-2025"
                    if isinstance(service, ServiceMsys)
                    else "macos-15-intel"
                    if isinstance(service, ServiceHomebrew)
                    else "ubuntu-24.04-arm"
                    if arch == "arm64"
                    else "ubuntu-24.04"
                ),
            )

    graph_job_ids = sorted(jobs)
    jobs["graph-result"] = {
        "name": "Orion graph result",
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
    jobs["publication-bootstrap"] = {
        "name": "Bootstrap Taskcluster publication group",
        "needs": ["plan"],
        "if": "always() && !cancelled() && "
        "fromJSON(needs.plan.outputs.plan_json).publish",
        "runs-on": "ubuntu-24.04",
        "environment": "communitytc",
        "permissions": {"actions": "read", "contents": "read"},
        "outputs": {"task_group": "${{ steps.bootstrap.outputs.task_group }}"},
        "steps": [
            {"uses": "actions/checkout@v5", "with": {"ref": HEAD_SHA}},
            {"uses": "actions/setup-python@v6", "with": {"python-version": "3.13"}},
            {"run": "python -m pip install -e services/orion-decision"},
            {
                "id": "bootstrap",
                "env": {
                    "TASKCLUSTER_ACCESS_TOKEN": (
                        "${{ secrets.TASKCLUSTER_GH_ORION_PUBLISHER_ACCESS_TOKEN }}"
                    ),
                    "TASKCLUSTER_CLIENT_ID": "project/fuzzing/gh-orion-publisher",
                    "TASKCLUSTER_ROOT_URL": "${{ vars.TASKCLUSTER_ROOT_URL }}",
                    "GITHUB_TOKEN": "${{ github.token }}",
                    "ORION_PLAN_JSON": "${{ needs.plan.outputs.plan_json }}",
                },
                "run": (
                    'printf \'%s\' "$ORION_PLAN_JSON" > "$RUNNER_TEMP/plan.json"\n'
                    "group=$(python -m orion_decision.gha_publish bootstrap "
                    '--plan-file "$RUNNER_TEMP/plan.json" '
                    '--output "$RUNNER_TEMP/group.json")\n'
                    'echo "task_group=$group" >> "$GITHUB_OUTPUT"'
                ),
            },
            {
                "uses": "actions/upload-artifact@v5",
                "if": "always()",
                "with": {
                    "name": (
                        "orion-publication-group-${{ github.run_id }}-"
                        "${{ github.run_attempt }}"
                    ),
                    "path": "${{ runner.temp }}/group.json",
                    "if-no-files-found": "ignore",
                    "retention-days": 7,
                },
            },
        ],
    }

    publish_condition = (
        "always() && !cancelled() && github.event_name != 'pull_request' && "
        "github.ref == 'refs/heads/master' && "
        "fromJSON(needs.plan.outputs.plan_json).publish"
    )
    publication_jobs: list[str] = []
    index_jobs_by_service: dict[str, list[str]] = {}
    docker_jobs_by_service: dict[str, str] = {}
    receipt_jobs: list[str] = []

    for service in sorted(services.values(), key=lambda item: item.name):
        if isinstance(service, ServiceTestOnly):
            continue
        selected_builds = [
            build_ids[(service.name, arch)] for arch in sorted(service.archs)
        ]
        selected_gate = " && ".join(
            f"(contains(fromJSON(needs.plan.outputs.selected_jobs), '{build}') && "
            f"needs.{build}.result == 'success')"
            for build in selected_builds
        )
        for arch in sorted(service.archs):
            build = build_ids[(service.name, arch)]
            index_id = job_id("index", service.name, arch)
            jobs[index_id] = {
                "name": f"Schedule {service.name} {arch} Taskcluster import",
                "needs": ["plan", "publication-bootstrap", build],
                "if": (
                    f"{publish_condition} && "
                    "needs.publication-bootstrap.result == 'success' && "
                    "contains(fromJSON(needs.plan.outputs.selected_jobs), "
                    f"'{build}') "
                    f"&& needs.{build}.result == 'success'"
                ),
                "uses": "./.github/workflows/publish-service.yml",
                "with": {
                    "operation": "index",
                    "service": service.name,
                    "arch": arch,
                    "revision": HEAD_SHA,
                    "plan_json": "${{ needs.plan.outputs.plan_json }}",
                    "task_group": (
                        "${{ needs.publication-bootstrap.outputs.task_group }}"
                    ),
                    "job_results": "${{ toJSON(needs) }}",
                },
                "secrets": "inherit",
            }
            index_jobs_by_service.setdefault(service.name, []).append(index_id)
            publication_jobs.append(index_id)

        if service.dockerfile is not None and not isinstance(
            service, (ServiceMsys, ServiceHomebrew)
        ):
            docker_id = job_id("publish_docker", service.name)
            docker_jobs_by_service[service.name] = docker_id
            jobs[docker_id] = {
                "name": f"Publish {service.name} Docker latest",
                "needs": ["plan", *selected_builds],
                "if": f"{publish_condition} && {selected_gate}",
                "concurrency": {
                    "group": (
                        f"orion-docker-latest-{service.name}-${{{{ github.ref }}}}"
                    ),
                    "cancel-in-progress": False,
                },
                "uses": "./.github/workflows/publish-service.yml",
                "with": {
                    "operation": "docker",
                    "service": service.name,
                    "arch": "",
                    "revision": HEAD_SHA,
                    "plan_json": "${{ needs.plan.outputs.plan_json }}",
                    "task_group": "",
                    "job_results": "${{ toJSON(needs) }}",
                },
                "secrets": "inherit",
            }
            publication_jobs.append(docker_id)

        receipt_id = job_id("receipt", service.name)
        receipt_needs = [
            "plan",
            "publication-bootstrap",
            *index_jobs_by_service[service.name],
        ]
        if service.name in docker_jobs_by_service:
            receipt_needs.append(docker_jobs_by_service[service.name])
        receipt_checks = [
            f"(needs.{index}.result == 'success' || "
            "!contains(fromJSON(needs.plan.outputs.selected_jobs), "
            f"'{build_ids[(service.name, arch)]}'))"
            for arch, index in zip(
                sorted(service.archs), index_jobs_by_service[service.name]
            )
        ]
        if service.name in docker_jobs_by_service:
            receipt_checks.append(
                f"(needs.{docker_jobs_by_service[service.name]}.result == 'success' || "
                "("
                + " && ".join(
                    "!contains(fromJSON(needs.plan.outputs.selected_docker_jobs), "
                    f"'{build}')"
                    for build in selected_builds
                )
                + "))"
            )
        selected_any = " || ".join(
            f"contains(fromJSON(needs.plan.outputs.selected_jobs), '{build}')"
            for build in selected_builds
        )
        jobs[receipt_id] = {
            "name": f"Create {service.name} Taskcluster publication receipt",
            "needs": receipt_needs,
            "if": f"{publish_condition} && "
            "needs.publication-bootstrap.result == 'success' && "
            f"({selected_any}) && " + " && ".join(receipt_checks),
            "uses": "./.github/workflows/publish-service.yml",
            "with": {
                "operation": "receipt",
                "service": service.name,
                "arch": "",
                "revision": HEAD_SHA,
                "plan_json": "${{ needs.plan.outputs.plan_json }}",
                "task_group": ("${{ needs.publication-bootstrap.outputs.task_group }}"),
                "job_results": "${{ toJSON(needs) }}",
            },
            "secrets": "inherit",
        }
        receipt_jobs.append(receipt_id)
        publication_jobs.append(receipt_id)

    jobs["publication-done"] = {
        "name": "Orion publication submissions complete",
        "needs": ["plan", "publication-bootstrap", "graph-result", *publication_jobs],
        "if": "always() && !cancelled() && "
        "fromJSON(needs.plan.outputs.plan_json).publish",
        "runs-on": "ubuntu-24.04",
        "environment": "communitytc",
        "permissions": {"actions": "read", "contents": "read"},
        "steps": [
            {"uses": "actions/checkout@v5", "with": {"ref": HEAD_SHA}},
            {"uses": "actions/setup-python@v6", "with": {"python-version": "3.13"}},
            {"run": "python -m pip install -e services/orion-decision"},
            {
                "name": "Close publication submissions",
                "env": {
                    "TASKCLUSTER_ACCESS_TOKEN": (
                        "${{ secrets.TASKCLUSTER_GH_ORION_PUBLISHER_ACCESS_TOKEN }}"
                    ),
                    "TASKCLUSTER_CLIENT_ID": "project/fuzzing/gh-orion-publisher",
                    "TASKCLUSTER_ROOT_URL": "${{ vars.TASKCLUSTER_ROOT_URL }}",
                    "GITHUB_TOKEN": "${{ github.token }}",
                    "ORION_PLAN_JSON": "${{ needs.plan.outputs.plan_json }}",
                    "ORION_JOB_RESULTS": "${{ toJSON(needs) }}",
                    "ORION_TASK_GROUP": (
                        "${{ needs.publication-bootstrap.outputs.task_group }}"
                    ),
                },
                "run": (
                    'printf \'%s\' "$ORION_PLAN_JSON" > "$RUNNER_TEMP/plan.json"\n'
                    "python -m orion_decision.gha_publish close "
                    '--plan-file "$RUNNER_TEMP/plan.json" '
                    '--task-group "$ORION_TASK_GROUP" '
                    '--output "$RUNNER_TEMP/publication-control.json"'
                ),
            },
            {
                "uses": "actions/upload-artifact@v5",
                "if": "always()",
                "with": {
                    "name": (
                        "orion-publication-control-${{ github.run_id }}-"
                        "${{ github.run_attempt }}"
                    ),
                    "path": "${{ runner.temp }}/publication-control.json",
                    "if-no-files-found": "error",
                    "retention-days": 7,
                },
            },
        ],
    }
    jobs["publication-workers"] = {
        "name": "Taskcluster worker ${{ matrix.worker }}",
        "needs": ["plan"],
        "if": "always() && !cancelled() && "
        "fromJSON(needs.plan.outputs.plan_json).publish",
        "runs-on": "ubuntu-24.04",
        "environment": "communitytc",
        "strategy": {"fail-fast": False, "matrix": {"worker": [1, 2]}},
        "permissions": {"actions": "read", "contents": "read"},
        "steps": [
            {"uses": "actions/checkout@v5", "with": {"ref": HEAD_SHA}},
            {"uses": "actions/setup-python@v6", "with": {"python-version": "3.13"}},
            {"run": "python -m pip install -e services/orion-decision"},
            {
                "name": "Write protected GitHub token file",
                "env": {
                    "GITHUB_TOKEN": "${{ github.token }}",
                    "ORION_GITHUB_TOKEN_FILE": "${{ runner.temp }}/orion-github-token",
                },
                "run": (
                    "umask 077\n"
                    'printf \'%s\' "$GITHUB_TOKEN" > "$ORION_GITHUB_TOKEN_FILE"\n'
                    'chmod 0600 "$ORION_GITHUB_TOKEN_FILE"'
                ),
            },
            {
                "name": "Run worker pool",
                "env": {
                    "TASKCLUSTER_ACCESS_TOKEN": (
                        "${{ secrets.TASKCLUSTER_CI_WORKER_ORION_GHA_ACCESS_TOKEN }}"
                    ),
                    "TASKCLUSTER_CLIENT_ID": "project/fuzzing/ci-worker-orion-gha",
                    "TASKCLUSTER_ROOT_URL": "${{ vars.TASKCLUSTER_ROOT_URL }}",
                    "GITHUB_TOKEN": "${{ github.token }}",
                    "ORION_GITHUB_TOKEN_FILE": "${{ runner.temp }}/orion-github-token",
                    "ORION_PLAN_JSON": "${{ needs.plan.outputs.plan_json }}",
                    "TC_WORKER_ID": (
                        "gh-orion-publish-${{ github.run_id }}-"
                        "${{ github.run_attempt }}-${{ matrix.worker }}"
                    ),
                },
                "run": (
                    'printf \'%s\' "$ORION_PLAN_JSON" > "$RUNNER_TEMP/plan.json"\n'
                    "python -m orion_decision.gha_publish worker-pool "
                    '--plan-file "$RUNNER_TEMP/plan.json" --timeout 16200'
                ),
            },
        ],
        "timeout-minutes": 360,
    }
    jobs["result"] = {
        "name": "Orion workflow result",
        "needs": [
            "plan",
            "graph-result",
            "publication-done",
            "publication-workers",
        ],
        "if": "always()",
        "runs-on": "ubuntu-latest",
        "steps": [
            {
                "name": "Require graph and publication success",
                "env": {
                    "ORION_GRAPH_RESULT": "${{ needs.graph-result.result }}",
                    "ORION_PUBLISH": "${{ needs.plan.outputs.publish }}",
                    "ORION_PUBLICATION_RESULT": "${{ needs.publication-done.result }}",
                    "ORION_WORKERS_RESULT": "${{ needs.publication-workers.result }}",
                },
                "run": (
                    "python - <<'PY'\n"
                    "import os, sys\n"
                    "if os.environ['ORION_GRAPH_RESULT'] != 'success':\n"
                    "    sys.exit('Selected Orion graph jobs did not all succeed')\n"
                    "if os.environ['ORION_PUBLISH'] == 'true':\n"
                    "    if os.environ['ORION_PUBLICATION_RESULT'] != 'success':\n"
                    "        sys.exit('Publication submissions failed')"
                    "\n"
                    "    if os.environ['ORION_WORKERS_RESULT'] != 'success':\n"
                    "        sys.exit('Workers did not drain')"
                    "\n"
                    "PY"
                ),
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
            "pull_request": {"types": ["opened", "synchronize", "reopened"]},
            "push": {"branches": ["master"]},
            "schedule": [{"cron": "0 5 * * 1"}],
            "workflow_dispatch": {
                "inputs": {
                    "force_services": {
                        "description": "Comma-separated service names to rebuild",
                        "required": False,
                        "type": "string",
                    },
                }
            },
        },
        "permissions": {"actions": "read", "contents": "read"},
        "jobs": {
            "plan": {
                "name": "Plan Orion graph",
                "runs-on": "ubuntu-latest",
                "outputs": {
                    "selected_jobs": "${{ steps.plan.outputs.selected_jobs }}",
                    "selected_docker_jobs": (
                        "${{ steps.plan.outputs.selected_docker_jobs }}"
                    ),
                    "publish": "${{ steps.plan.outputs.publish }}",
                    "plan_json": "${{ steps.plan.outputs.plan_json }}",
                },
                "steps": [
                    {
                        "uses": "actions/checkout@v5",
                        "with": {"ref": HEAD_SHA, "fetch-depth": 0},
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
                            "ORION_REVISION": HEAD_SHA,
                            "ORION_EVENT": "${{ github.event_name }}",
                            "ORION_BRANCH": "${{ github.ref_name }}",
                            "ORION_BASE_REVISION": (
                                "${{ github.event.pull_request.base.sha }}"
                            ),
                        },
                        "run": (
                            "plan=$(python -m orion_decision.gha_plan --repo . "
                            '--revision "$ORION_REVISION" '
                            '--event "$ORION_EVENT" '
                            '--branch "$ORION_BRANCH" '
                            '--base-revision "$ORION_BASE_REVISION" '
                            "--baseline-from-taskcluster "
                            '--force-services "$ORION_FORCE_SERVICES")\n'
                            'echo "plan_json=$plan" >> "$GITHUB_OUTPUT"\n'
                            'selected=$(python -c "import json,sys; '
                            "print(json.dumps(json.load(sys.stdin)['selected_jobs'], "
                            "separators=(',', ':')))\" <<< \"$plan\")\n"
                            'echo "selected_jobs=$selected" >> "$GITHUB_OUTPUT"\n'
                            'docker_selected=$(python -c "import json,sys; '
                            "print(json.dumps(json.load(sys.stdin)['selected_docker_jobs']))"
                            '" <<< "$plan")\n'
                            'echo "selected_docker_jobs=$docker_selected" '
                            '>> "$GITHUB_OUTPUT"\n'
                            'publish=$(python -c "import json,sys; '
                            "print(str(json.load(sys.stdin)['publish']).lower())"
                            '" <<< "$plan")\n'
                            'echo "publish=$publish" >> "$GITHUB_OUTPUT"'
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
