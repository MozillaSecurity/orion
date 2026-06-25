"""Download only changed Docker parents built by the current Actions run."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


def download_dependencies(
    plan: dict,
    service: str,
    arch: str,
    run_id: str,
    repository: str,
    token: str,
    output: Path,
) -> list[str]:
    """Download the current-run archives for this service's dirty Docker parents."""
    spec = plan["services"][service]
    artifacts = []
    for parent in spec.get("image_dependencies", spec["dependencies"]):
        parent_spec = plan["services"][parent]
        if parent_spec["kind"] != "docker" or parent not in plan["dirty"]:
            continue
        parent_arch = arch if arch in parent_spec["archs"] else parent_spec["archs"][0]
        artifact = f"image-{parent}-{parent_arch}"
        destination = output / artifact
        destination.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "gh",
                "run",
                "download",
                run_id,
                "--repo",
                repository,
                "--name",
                artifact,
                "--dir",
                str(destination),
            ],
            check=True,
            env={**os.environ, "GH_TOKEN": token},
        )
        artifacts.append(artifact)
    return artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=Path("plan.json"))
    parser.add_argument("--service", required=True)
    parser.add_argument("--arch", required=True, choices=["amd64", "arm64"])
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--token", default=os.environ.get("GH_TOKEN", ""))
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    args = parser.parse_args()
    if not all((args.run_id, args.repository, args.token)):
        parser.error("run ID, repository, and GH_TOKEN are required")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    download_dependencies(
        plan,
        args.service,
        args.arch,
        args.run_id,
        args.repository,
        args.token,
        args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
