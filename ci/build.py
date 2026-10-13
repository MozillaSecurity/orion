"""Build service archives on Actions runners, using this run's rebuilt parents."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def build(plan: dict, service: str, arch: str, artifacts: Path, output: Path) -> Path:
    spec = plan["services"][service]
    if spec["kind"] != "docker" or arch not in spec["archs"]:
        raise ValueError(f"Unsupported Docker build: {service}/{arch}")
    # Podman uses the local image store for FROM (unlike an isolated buildx builder).
    # A changed parent must come from this workflow; never silently use latest.
    for parent in spec.get("image_dependencies", spec["dependencies"]):
        parent_spec = plan["services"][parent]
        if parent_spec["kind"] != "docker":
            continue
        parent_arch = arch if arch in parent_spec["archs"] else parent_spec["archs"][0]
        if parent in plan["dirty"]:
            archive = (
                artifacts
                / f"image-{parent}-{parent_arch}"
                / f"{parent}-{parent_arch}.tar.zst"
            )
            if not archive.is_file():
                raise FileNotFoundError(f"Missing rebuilt dependency: {archive}")
            run("podman", "load", "--input", str(archive))
            run(
                "podman",
                "tag",
                f"docker.io/mozillasecurity/{parent}:latest-{parent_arch}",
                f"docker.io/mozillasecurity/{parent}:latest",
            )
        else:
            parent_tag = f"docker.io/mozillasecurity/{parent}:latest-{parent_arch}"
            run("podman", "pull", parent_tag)
            run(
                "podman",
                "tag",
                parent_tag,
                f"docker.io/mozillasecurity/{parent}:latest",
            )
    tag = f"docker.io/mozillasecurity/{service}:latest-{arch}"
    run(
        "podman",
        "build",
        "--pull=missing",
        "--platform",
        f"linux/{arch}",
        "--tag",
        tag,
        "--file",
        spec["dockerfile"],
        spec["context"],
    )
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"{service}-{arch}.tar"
    run("podman", "save", "--format", "docker-archive", "--output", str(archive), tag)
    run("zstd", "-T0", "--rm", str(archive))
    return archive.with_suffix(".tar.zst")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=Path("plan.json"))
    parser.add_argument("--service", required=True)
    parser.add_argument("--arch", required=True, choices=["amd64", "arm64"])
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--output", type=Path, default=Path("output"))
    args = parser.parse_args()
    build(
        json.loads(args.plan.read_text()),
        args.service,
        args.arch,
        args.artifacts,
        args.output,
    )


if __name__ == "__main__":
    main()
