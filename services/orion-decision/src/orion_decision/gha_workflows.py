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
    jobs["result"] = {
        "name": "Orion workflow result",
        "needs": [
            "plan",
            "graph-result",
            "publication-manifest",
            "publication-worker",
        ],
        "if": "always()",
        "runs-on": "ubuntu-latest",
        "steps": [
            {
                "name": "Require graph and publication success",
                "env": {
                    "ORION_GRAPH_RESULT": "${{ needs.graph-result.result }}",
                    "ORION_PUBLISH": "${{ needs.plan.outputs.publish }}",
                    "ORION_MANIFEST_RESULT": "${{ needs.publication-manifest.result }}",
                    "ORION_WORKER_RESULT": "${{ needs.publication-worker.result }}",
                },
                "run": (
                    "python - <<'PY'\n"
                    "import os, sys\n"
                    "if os.environ['ORION_GRAPH_RESULT'] != 'success':\n"
                    "    sys.exit('Selected Orion graph jobs did not all succeed')\n"
                    "if os.environ['ORION_PUBLISH'] == 'true':\n"
                    "    if os.environ['ORION_MANIFEST_RESULT'] != 'success':\n"
                    "        sys.exit('Taskcluster publication manifest "
                    "was not created')\n"
                    "    if os.environ['ORION_WORKER_RESULT'] != 'success':\n"
                    "        sys.exit('Taskcluster artifact imports "
                    "did not complete')\n"
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
            "publication-manifest": {
                "name": "Create Taskcluster publication manifest",
                "needs": ["plan", "graph-result", "publish-docker"],
                "if": (
                    "always() && !cancelled() && "
                    "needs.graph-result.result == 'success' && "
                    "(needs.publish-docker.result == 'success' || "
                    "needs.plan.outputs.selected_docker_jobs == '[]') && "
                    "github.event_name != 'pull_request' && "
                    "github.ref == 'refs/heads/master' && "
                    "fromJSON(needs.plan.outputs.plan_json).publish"
                ),
                "runs-on": "ubuntu-24.04",
                "permissions": {"actions": "read", "contents": "read"},
                "steps": [
                    {
                        "uses": "actions/checkout@v5",
                        "with": {"ref": HEAD_SHA, "fetch-depth": 0},
                    },
                    {
                        "uses": "actions/setup-python@v6",
                        "with": {"python-version": "3.13"},
                    },
                    {"run": "python -m pip install -e services/orion-decision"},
                    {
                        "name": "Reject stale publication before manifest creation",
                        "env": {
                            "GITHUB_TOKEN": "${{ github.token }}",
                            "ORION_REVISION": HEAD_SHA,
                            "ORION_BRANCH": "${{ github.ref_name }}",
                        },
                        "run": (
                            "python -m orion_decision.gha_run check-head "
                            '--repository "$GITHUB_REPOSITORY" '
                            '--branch "$ORION_BRANCH" '
                            '--revision "$ORION_REVISION"'
                        ),
                    },
                    {
                        "name": "Write plan and bind exact build artifacts",
                        "env": {
                            "GITHUB_TOKEN": "${{ github.token }}",
                            "ORION_PLAN_JSON": "${{ needs.plan.outputs.plan_json }}",
                        },
                        "run": (
                            "printf '%s' \"$ORION_PLAN_JSON\" "
                            '> "$RUNNER_TEMP/plan.json"\n'
                            "python -m orion_decision.gha_publish manifest "
                            '--plan-file "$RUNNER_TEMP/plan.json" '
                            '--output "$RUNNER_TEMP/manifest.json"'
                        ),
                    },
                    {
                        "uses": "actions/upload-artifact@v5",
                        "with": {
                            "name": (
                                "orion-publication-manifest-${{ github.run_id }}-"
                                "${{ github.run_attempt }}"
                            ),
                            "path": "${{ runner.temp }}/manifest.json",
                            "if-no-files-found": "error",
                            "retention-days": 7,
                        },
                    },
                ],
            },
            "publication-worker": {
                "name": "Import Taskcluster publication artifacts",
                "needs": ["plan", "publication-manifest"],
                "if": (
                    "always() && !cancelled() && "
                    "needs.publication-manifest.result == 'success' && "
                    "github.event_name != 'pull_request' && "
                    "github.ref == 'refs/heads/master' && "
                    "fromJSON(needs.plan.outputs.plan_json).publish"
                ),
                "runs-on": "ubuntu-24.04",
                "permissions": {"actions": "read", "contents": "read"},
                "env": {
                    "TASKCLUSTER_ACCESS_TOKEN": (
                        "${{ secrets.TASKCLUSTER_ACCESS_TOKEN }}"
                    ),
                    "TASKCLUSTER_CLIENT_ID": (
                        "project/fuzzing/worker-orion-gha-publish-gh"
                    ),
                    "TASKCLUSTER_ROOT_URL": (
                        "https://community-tc.services.mozilla.com"
                    ),
                    "TC_WORKER_ID": (
                        "gh-orion-publish-${{ github.run_id }}-"
                        "${{ github.run_attempt }}"
                    ),
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
                    {"run": "python -m pip install -e services/orion-decision"},
                    {
                        "uses": "actions/download-artifact@v5",
                        "with": {
                            "name": (
                                "orion-publication-manifest-${{ github.run_id }}-"
                                "${{ github.run_attempt }}"
                            ),
                            "path": "${{ runner.temp }}/orion-publication",
                        },
                    },
                    {
                        "name": "Write protected GitHub token file",
                        "env": {
                            "GITHUB_TOKEN": "${{ github.token }}",
                            "ORION_GITHUB_TOKEN_FILE": (
                                "${{ runner.temp }}/orion-github-token"
                            ),
                        },
                        "run": (
                            "umask 077\n"
                            "printf '%s' \"$GITHUB_TOKEN\" "
                            '> "$ORION_GITHUB_TOKEN_FILE"\n'
                            'chmod 0600 "$ORION_GITHUB_TOKEN_FILE"'
                        ),
                    },
                    {
                        "name": "Ensure exact import tasks exist",
                        "env": {
                            "ORION_RUN_ID": "${{ github.run_id }}",
                            "ORION_RUN_ATTEMPT": "${{ github.run_attempt }}",
                        },
                        "run": (
                            "# Webhook decisions can run before manifest upload.\n"
                            "# Deterministic IDs make this idempotent for every run.\n"
                            "group=$(python -c 'from orion_decision.gha_publish "
                            "import artifact_task_id; "
                            "import os; print(artifact_task_id("
                            'os.environ["ORION_RUN_ID"], '
                            'os.environ["ORION_RUN_ATTEMPT"], "decision"))\')\n'
                            "python -m orion_decision.gha_publish schedule "
                            "--manifest-file "
                            '"$RUNNER_TEMP/orion-publication/manifest.json" '
                            '--task-group "$group"'
                        ),
                    },
                    {
                        "name": "Run worker and require every exact import",
                        "env": {
                            "ORION_GITHUB_TOKEN_FILE": (
                                "${{ runner.temp }}/orion-github-token"
                            ),
                        },
                        "run": (
                            "set +e\n"
                            ".github/scripts/start-worker.sh > "
                            '"$RUNNER_TEMP/generic-worker.log" 2>&1 &\n'
                            "worker_pid=$!\n"
                            "python -m orion_decision.gha_publish monitor "
                            "--manifest-file "
                            '"$RUNNER_TEMP/orion-publication/manifest.json" '
                            "--timeout 3600 > "
                            '"$RUNNER_TEMP/publication-monitor.log" 2>&1 &\n'
                            "monitor_pid=$!\n"
                            'wait "$monitor_pid"\n'
                            "monitor_status=$?\n"
                            'if kill -0 "$worker_pid" 2>/dev/null; then '
                            'if [ "$monitor_status" -eq 0 ]; then '
                            'kill -USR1 "$worker_pid"; '
                            'else kill -TERM "$worker_pid"; fi; fi\n'
                            'wait "$worker_pid"\n'
                            'cat "$RUNNER_TEMP/generic-worker.log"\n'
                            'cat "$RUNNER_TEMP/publication-monitor.log"\n'
                            'exit "$monitor_status"'
                        ),
                    },
                ],
            },
            "publish-docker": {
                "name": "Publish Orion Docker manifests",
                "needs": ["plan", "graph-result"],
                "if": (
                    "always() && !cancelled() && "
                    "needs.graph-result.result == 'success' && "
                    "needs.plan.outputs.selected_docker_jobs != '[]' && "
                    "github.event_name != 'pull_request' && "
                    "github.ref == 'refs/heads/master' && "
                    "fromJSON(needs.plan.outputs.plan_json).publish"
                ),
                "runs-on": "ubuntu-24.04",
                "environment": "dockerhub",
                "concurrency": {
                    "group": "orion-docker-latest-${{ github.ref }}",
                    "cancel-in-progress": False,
                },
                "permissions": {"actions": "read", "contents": "read"},
                "steps": [
                    {
                        "uses": "actions/checkout@v5",
                        "with": {"ref": HEAD_SHA, "fetch-depth": 0},
                    },
                    {
                        "uses": "actions/setup-python@v6",
                        "with": {"python-version": "3.13"},
                    },
                    {"run": "python -m pip install -e services/orion-decision"},
                    {
                        "name": "Write plan and install zstd",
                        "env": {
                            "ORION_PLAN_JSON": "${{ needs.plan.outputs.plan_json }}"
                        },
                        "run": (
                            "printf '%s' \"$ORION_PLAN_JSON\" > "
                            '"$RUNNER_TEMP/plan.json"\n'
                            "sudo apt-get update && sudo apt-get install --yes zstd"
                        ),
                    },
                    {
                        "name": "Reject stale branch publication",
                        "env": {
                            "GITHUB_TOKEN": "${{ github.token }}",
                            "ORION_REVISION": HEAD_SHA,
                            "ORION_BRANCH": "${{ github.ref_name }}",
                        },
                        "run": (
                            "python -m orion_decision.gha_run check-head "
                            '--repository "$GITHUB_REPOSITORY" '
                            '--branch "$ORION_BRANCH" '
                            '--revision "$ORION_REVISION"'
                        ),
                    },
                    {"uses": "docker/setup-buildx-action@v3"},
                    {
                        "uses": "docker/login-action@v3",
                        "with": {
                            "username": "${{ vars.DOCKERHUB_USERNAME }}",
                            "password": "${{ secrets.DOCKERHUB_TOKEN }}",
                        },
                    },
                    {
                        "name": "Push staging images and publish latest manifests",
                        "env": {"GITHUB_TOKEN": "${{ github.token }}"},
                        "run": (
                            "python -m orion_decision.gha_run publish "
                            '--repo . --plan-file "$RUNNER_TEMP/plan.json"'
                        ),
                    },
                    {
                        "name": "Record published image digests",
                        "uses": "actions/upload-artifact@v5",
                        "with": {
                            "name": (
                                "orion-published-image-digests-${{ github.run_id }}"
                                "-${{ github.run_attempt }}"
                            ),
                            "path": "${{ runner.temp }}/published-images.json",
                            "if-no-files-found": "error",
                            "retention-days": 90,
                        },
                    },
                ],
            },
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
