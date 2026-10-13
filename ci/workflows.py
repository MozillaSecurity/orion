"""Generate the checked-in GitHub Actions workflow from Orion's service graph."""

# YAML expressions and embedded shell snippets are long by design.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import yaml

from .graph import ServiceGraph, _git_files

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = Path(".github/workflows/orion.yml")
BUILD_WORKFLOW = "./.github/workflows/build-service.yml"
BUILDABLE = {"docker", "msys", "homebrew"}


class WorkflowDumper(yaml.SafeDumper):
    """Keep embedded shell programs readable in generated workflow YAML."""


def _represent_string(dumper: WorkflowDumper, value: str) -> yaml.ScalarNode:
    return dumper.represent_scalar(
        "tag:yaml.org,2002:str", value, style="|" if "\n" in value else None
    )


WorkflowDumper.add_representer(str, _represent_string)


def _job_id(name: str) -> str:
    return "build_" + re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")


def _service_graph(root: Path) -> ServiceGraph:
    return ServiceGraph(root, _git_files(root))


def _json_output(expression: str) -> str:
    return f"${{{{ {expression} }}}}"


def generate(root: Path = ROOT) -> dict[str, Any]:
    graph = _service_graph(root)
    services = graph.services
    buildable = {
        name: node for name, node in services.items() if node.kind in BUILDABLE
    }

    jobs: dict[str, Any] = {}
    jobs["plan"] = {
        "runs-on": "ubuntu-24.04",
        "outputs": {
            "dirty": _json_output("steps.plan.outputs.dirty"),
            "test_matrix": _json_output("steps.plan.outputs.test_matrix"),
            "recipe_matrix": _json_output("steps.plan.outputs.recipe_matrix"),
            "publish_matrix": _json_output("steps.plan.outputs.publish_matrix"),
        },
        "steps": [
            {"uses": "actions/checkout@v6", "with": {"fetch-depth": 0}},
            {
                "uses": "astral-sh/setup-uv@v10",
                "with": {
                    "python-version": "3.12",
                    "cache-dependency-glob": "ci/uv.lock",
                },
            },
            {
                "name": "Install workflow tools",
                "run": "uv sync --project ci --locked --no-dev",
            },
            {
                "id": "baseline",
                "name": "Find the last successfully published revision",
                "env": {"GH_TOKEN": _json_output("github.token")},
                "run": "uv run --project ci --locked --no-dev python -m ci.baseline",
            },
            {
                "id": "plan",
                "name": "Plan tests and image builds",
                "env": {
                    "BASE": _json_output("steps.baseline.outputs.base"),
                    "REBUILD_ALL": _json_output("inputs.rebuild_all"),
                },
                "shell": "bash",
                "run": (
                    "all_args=()\n"
                    'if [[ "$GITHUB_EVENT_NAME" == "schedule" || '
                    '("$GITHUB_EVENT_NAME" == "workflow_dispatch" && "$REBUILD_ALL" == "true") ]]; then\n'
                    "  all_args+=(--all)\n"
                    "fi\n"
                    'uv run --project ci --locked --no-dev python -m ci.plan --base "$BASE" --head "$GITHUB_SHA" '
                    '--output plan.json "${all_args[@]}"\n'
                    "uv run --project ci --locked --no-dev python - <<'PY'\n"
                    "import json, os\n"
                    "from pathlib import Path\n"
                    "plan = json.loads(Path('plan.json').read_text())\n"
                    "services = plan['services']\n"
                    "buildable = {'docker', 'msys', 'homebrew'}\n"
                    "publish = [{'service': name} for name in plan['dirty'] if services[name]['kind'] in buildable]\n"
                    "recipes = [{'recipe': name} for name in plan['recipes']]\n"
                    "tests = [item for item in plan['test_matrix'] if item['service'] != 'orion']\n"
                    "root_tests = plan['services'].get('orion', {}).get('tests', [])\n"
                    "for item in root_tests:\n"
                    "    tests.append({'service': 'orion', 'path': '.', 'python': item.get('python', '3.10'), 'toxenv': item.get('toxenv', 'lint'), 'name': item.get('name', 'root lint')})\n"
                    "tests = tests or [{'service': '', 'path': '.', 'python': '3.10', 'toxenv': 'lint', 'name': ''}]\n"
                    "with open(os.environ['GITHUB_OUTPUT'], 'a') as output:\n"
                    "    output.write('dirty=' + json.dumps(plan['dirty'], separators=(',', ':')) + '\\n')\n"
                    "    output.write('test_matrix=' + json.dumps({'include': tests}, separators=(',', ':')) + '\\n')\n"
                    "    output.write('recipe_matrix=' + json.dumps({'include': recipes or [{'recipe': ''}]}, separators=(',', ':')) + '\\n')\n"
                    "    output.write('publish_matrix=' + json.dumps({'include': publish or [{'service': ''}]}, separators=(',', ':')) + '\\n')\n"
                    "PY"
                ),
            },
            {
                "uses": "actions/upload-artifact@v4",
                "with": {
                    "name": "orion-plan",
                    "path": "plan.json",
                    "retention-days": 2,
                },
            },
        ],
    }

    jobs["tests"] = {
        "needs": ["plan"],
        "if": "${{ always() && needs.plan.result == 'success' }}",
        "runs-on": "ubuntu-24.04",
        "strategy": {
            "fail-fast": False,
            "matrix": _json_output(
                'fromJSON(needs.plan.outputs.test_matrix || \'{"include":[{"service":"","path":".","python":"3.10","toxenv":"lint","name":""}]}\')'
            ),
        },
        "steps": [
            {"if": "${{ matrix.service != '' }}", "uses": "actions/checkout@v6"},
            {
                "if": "${{ matrix.service != '' }}",
                "uses": "astral-sh/setup-uv@v10",
                "with": {
                    "python-version": _json_output("matrix.python"),
                    "cache-dependency-glob": "ci/uv.lock",
                },
            },
            {
                "if": "${{ matrix.service != '' }}",
                "uses": "actions/setup-python@v6",
                "with": {"python-version": _json_output("matrix.python")},
            },
            {
                "if": "${{ matrix.service != '' }}",
                "name": "Run ${{ matrix.name }}",
                "working-directory": _json_output("matrix.path"),
                "run": "uv tool run tox -e ${{ matrix.toxenv }}",
            },
        ],
    }
    jobs["ci_tests"] = {
        "needs": ["plan"],
        "if": "${{ always() && needs.plan.result == 'success' }}",
        "runs-on": "ubuntu-24.04",
        "steps": [
            {"uses": "actions/checkout@v6"},
            {
                "uses": "astral-sh/setup-uv@v10",
                "with": {
                    "python-version": "3.12",
                    "cache-dependency-glob": "ci/uv.lock",
                },
            },
            {
                "name": "Install CI test dependencies",
                "run": "uv sync --project ci --locked",
            },
            {
                "name": "Test planner, builder, workflow and publisher",
                "run": "uv run --project ci --locked python -m pytest -q ci/tests",
            },
        ],
    }
    jobs["test_gate"] = {
        "needs": ["tests", "ci_tests"],
        "if": "${{ always() }}",
        "runs-on": "ubuntu-24.04",
        "steps": [
            {
                "name": "Require all test jobs to pass",
                "env": {"NEEDS": _json_output("toJSON(needs)")},
                "run": "python -c \"import json,os,sys; s=[j['result'] for j in json.loads(os.environ['NEEDS']).values()]; sys.exit(any(x in {'failure','cancelled'} for x in s))\"",
            }
        ],
    }
    jobs["recipes"] = {
        "needs": ["plan"],
        "if": "${{ always() && needs.plan.result == 'success' }}",
        "runs-on": "ubuntu-24.04",
        "strategy": {
            "fail-fast": False,
            "matrix": _json_output(
                'fromJSON(needs.plan.outputs.recipe_matrix || \'{"include":[{"recipe":""}]}\')'
            ),
        },
        "steps": [
            {"if": "${{ matrix.recipe != '' }}", "uses": "actions/checkout@v6"},
            {
                "if": "${{ matrix.recipe != '' }}",
                "name": "Install Podman",
                "run": "sudo apt-get update && sudo apt-get install -y podman",
            },
            {
                "name": "Test Linux recipe ${{ matrix.recipe }}",
                "if": "${{ matrix.recipe != '' }}",
                "shell": "bash",
                "run": (
                    'recipe="${{ matrix.recipe }}"\n'
                    'dockerfile="services/test-recipes/Dockerfile-${recipe%.sh}"\n'
                    'if [[ ! -f "$dockerfile" ]]; then dockerfile=services/test-recipes/Dockerfile; fi\n'
                    'podman build --file "$dockerfile" --build-arg "recipe=$recipe" .'
                ),
            },
        ],
    }
    jobs["recipe_gate"] = {
        "needs": ["recipes"],
        "if": "${{ always() }}",
        "runs-on": "ubuntu-24.04",
        "steps": [
            {
                "name": "Require all recipe jobs to pass",
                "env": {"RESULT": _json_output("needs.recipes.result")},
                "run": 'test "$RESULT" != failure && test "$RESULT" != cancelled',
            }
        ],
    }

    for name, node in sorted(buildable.items()):
        needs = ["plan", "test_gate", "recipe_gate"]
        needs.extend(
            _job_id(dep) for dep in sorted(node.dependencies) if dep in buildable
        )
        needs = list(dict.fromkeys(needs))
        need_results = "!contains(needs.*.result, 'failure') && !contains(needs.*.result, 'cancelled')"
        job: dict[str, Any] = {
            "needs": needs,
            "if": (
                "${{ always() && "
                + need_results
                + " && contains(fromJSON(needs.plan.outputs.dirty || '[]'), '"
                + name
                + "') }}"
            ),
            "uses": BUILD_WORKFLOW,
            "with": {"service": name, "kind": node.kind},
        }
        if node.kind == "docker":
            job["strategy"] = {"fail-fast": False, "matrix": {"arch": node.archs}}
            job["with"]["arch"] = _json_output("matrix.arch")
        else:
            job["with"]["arch"] = "amd64"
            if node.base:
                job["with"]["base"] = node.base
        jobs[_job_id(name)] = job

    publish_needs = [
        "plan",
        "test_gate",
        "recipe_gate",
        *(_job_id(name) for name in sorted(buildable)),
    ]
    jobs["publish"] = {
        "needs": publish_needs,
        "if": (
            "${{ always() && github.ref == 'refs/heads/main' && "
            "github.event_name != 'pull_request' && "
            "!contains(needs.*.result, 'failure') && !contains(needs.*.result, 'cancelled') }}"
        ),
        "strategy": {
            "fail-fast": False,
            "matrix": _json_output(
                'fromJSON(needs.plan.outputs.publish_matrix || \'{"include":[{"service":""}]}\')'
            ),
        },
        "runs-on": "ubuntu-24.04",
        "env": {
            "TASKCLUSTER_CLIENT_ID": _json_output("secrets.TASKCLUSTER_CLIENT_ID"),
            "TASKCLUSTER_ACCESS_TOKEN": _json_output(
                "secrets.TASKCLUSTER_ACCESS_TOKEN"
            ),
            "DOCKERHUB_USERNAME": _json_output("secrets.DOCKERHUB_USERNAME"),
            "DOCKERHUB_TOKEN": _json_output("secrets.DOCKERHUB_TOKEN"),
            "TASKCLUSTER_ROOT_URL": _json_output(
                "vars.TASKCLUSTER_ROOT_URL || 'https://firefox-ci-tc.services.mozilla.com'"
            ),
        },
        "steps": [
            {"if": "${{ matrix.service != '' }}", "uses": "actions/checkout@v6"},
            {
                "if": "${{ matrix.service != '' }}",
                "uses": "astral-sh/setup-uv@v10",
                "with": {
                    "python-version": "3.12",
                    "cache-dependency-glob": "ci/uv.lock",
                },
            },
            {
                "if": "${{ matrix.service != '' }}",
                "name": "Install publisher dependencies",
                "run": "uv sync --project ci --locked --no-dev",
            },
            {
                "if": "${{ matrix.service != '' }}",
                "name": "Install Podman and zstd",
                "run": "sudo apt-get update && sudo apt-get install -y podman zstd",
            },
            {
                "if": "${{ matrix.service != '' }}",
                "name": "Download plan",
                "uses": "actions/download-artifact@v5",
                "with": {"name": "orion-plan", "path": "."},
            },
            {
                "if": "${{ matrix.service != '' }}",
                "name": "Download exact service artifacts",
                "env": {"GH_TOKEN": _json_output("github.token")},
                "run": (
                    "uv run --project ci --locked --no-dev python -m ci.download_publication --plan plan.json "
                    "--service '${{ matrix.service }}' --run-id '${{ github.run_id }}' "
                    "--repository '${{ github.repository }}' --token \"$GH_TOKEN\" "
                    "--output artifacts"
                ),
            },
            {
                "if": "${{ matrix.service != '' }}",
                "name": "Publish ${{ matrix.service }}",
                "run": "uv run --project ci --locked --no-dev python -m ci.publish --plan plan.json --artifacts artifacts --service '${{ matrix.service }}'",
            },
        ],
    }
    jobs["complete"] = {
        "needs": list(jobs.keys()),
        "if": "${{ always() }}",
        "runs-on": "ubuntu-24.04",
        "steps": [
            {
                "name": "Fail the required check if any job failed or was cancelled",
                "env": {"NEEDS": _json_output("toJSON(needs)")},
                "run": "python -c \"import json,os,sys; s=[j['result'] for j in json.loads(os.environ['NEEDS']).values()]; sys.exit(any(x in {'failure','cancelled'} for x in s))\"",
            }
        ],
    }

    return {
        "name": "Orion CI and builds",
        "on": {
            "push": {"branches": ["main"]},
            "pull_request": {"branches": ["main"]},
            "workflow_dispatch": {
                "inputs": {
                    "rebuild_all": {
                        "description": "Rebuild every image and rerun recipe checks",
                        "required": False,
                        "default": False,
                        "type": "boolean",
                    }
                }
            },
            "schedule": [{"cron": "17 5 * * 1"}],
        },
        "permissions": {"actions": "read", "contents": "read"},
        "concurrency": {
            "group": "orion-${{ github.ref }}",
            "cancel-in-progress": _json_output("github.event_name == 'pull_request'"),
        },
        "jobs": jobs,
    }


def render(root: Path = ROOT) -> str:
    return yaml.dump(generate(root), Dumper=WorkflowDumper, sort_keys=False, width=110)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--write", action="store_true", help="write the generated workflow"
    )
    parser.add_argument(
        "--check", action="store_true", help="fail if the generated workflow is stale"
    )
    args = parser.parse_args()
    destination = args.root / WORKFLOW
    generated = render(args.root)
    if args.write:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(generated)
        return 0
    if args.check:
        if not destination.is_file() or destination.read_text() != generated:
            raise SystemExit(
                f"{WORKFLOW} is stale; run uv run --project ci --locked --no-dev "
                "python -m ci.workflows --write"
            )
        return 0
    print(generated, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
