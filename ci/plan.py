"""Create a deterministic change-based Orion CI build plan."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

from .graph import ServiceGraph


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def _changed_paths(root: Path, base: str, head: str) -> list[str]:
    output = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "diff",
            "--name-only",
            "--diff-filter=ACDMRTUXB",
            "-z",
            f"{base}...{head}",
        ],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    return sorted(path.decode() for path in output.split(b"\0") if path)


def build_plan(
    root: Path, base: str = "", head: str = "HEAD", all_services: bool = False
) -> dict:
    root = root.resolve()
    graph = ServiceGraph(root)
    head_sha = _git(root, "rev-parse", "--verify", f"{head}^{{commit}}")
    if all_services or not base:
        changed_paths = sorted(graph.tracked)
    else:
        changed_paths = _changed_paths(root, base, head)

    # Pipeline and planner changes can alter build semantics, so bootstrap all
    # image jobs when any of those control files changes.
    if any(
        path.startswith("ci/") or path.startswith(".github/workflows/")
        for path in changed_paths
    ):
        all_services = True
    if all_services:
        changed_paths = sorted(graph.tracked)

    result = graph.plan(changed_paths)
    result.update(
        {
            "base": base or None,
            "head": head_sha,
            "revision": head_sha,
            "changed_paths": changed_paths,
        }
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument(
        "--base", default="", help="base revision; omitted means full build"
    )
    parser.add_argument("--head", default="HEAD", help="head revision to plan")
    parser.add_argument("--all", action="store_true", help="build all services")
    parser.add_argument("--output", type=Path, help="write JSON to this file")
    args = parser.parse_args(argv)
    plan = build_plan(args.repo, args.base, args.head, args.all)
    rendered = json.dumps(plan, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
