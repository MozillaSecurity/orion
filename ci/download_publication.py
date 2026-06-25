"""Download only the exact build artifacts needed to publish one service."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


def download_publication(
    plan: dict,
    service: str,
    run_id: str,
    repository: str,
    token: str,
    output: Path,
) -> list[str]:
    """Fetch the service's exact architecture artifact names from this run."""
    spec = plan["services"][service]
    if spec["kind"] == "docker":
        names = [f"image-{service}-{arch}" for arch in spec["archs"]]
    elif spec["kind"] == "msys":
        names = [f"image-{service}-msys"]
    else:
        raise ValueError(f"Unsupported publication kind: {spec['kind']}")
    destination = output / service
    destination.mkdir(parents=True, exist_ok=True)
    for name in names:
        subprocess.run(
            [
                "gh",
                "run",
                "download",
                run_id,
                "--repo",
                repository,
                "--name",
                name,
                "--dir",
                str(destination),
            ],
            check=True,
            env={**os.environ, "GH_TOKEN": token},
        )
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=Path("plan.json"))
    parser.add_argument("--service", required=True)
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--token", default=os.environ.get("GH_TOKEN", ""))
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    args = parser.parse_args()
    if not all((args.run_id, args.repository, args.token)):
        parser.error("run ID, repository, and GH_TOKEN are required")
    download_publication(
        json.loads(args.plan.read_text(encoding="utf-8")),
        args.service,
        args.run_id,
        args.repository,
        args.token,
        args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
