"""Select the last successfully published revision, including missed/failed pushes."""

from __future__ import annotations

import json
import os
import subprocess
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def previous_success(repository: str, token: str, current_run: str) -> str | None:
    url = (
        f"https://api.github.com/repos/{repository}/actions/workflows/orion.yml/runs"
        "?branch=main&status=success&per_page=100"
    )
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            runs = json.load(response)["workflow_runs"]
    except HTTPError as exc:
        if exc.code == 404:  # First run, workflow has no published baseline yet.
            return None
        raise
    for run in runs:
        if (
            str(run["id"]) != current_run
            and run.get("conclusion") == "success"
            and run["event"] in {"push", "schedule", "workflow_dispatch"}
        ):
            sha = run["head_sha"]
            if (
                subprocess.run(
                    ["git", "merge-base", "--is-ancestor", sha, "HEAD"]
                ).returncode
                == 0
            ):
                return sha
    return None


def main() -> None:
    event = json.loads(open(os.environ["GITHUB_EVENT_PATH"]).read())
    name = os.environ["GITHUB_EVENT_NAME"]
    if name == "pull_request":
        # Checkout tests the merge commit; compare to the PR's base revision.
        base = event["pull_request"]["base"]["sha"]
    elif name == "schedule" or event.get("inputs", {}).get("rebuild_all") in {
        True,
        "true",
    }:
        base = None
    elif os.environ["GITHUB_REF"] == "refs/heads/main":
        base = previous_success(
            os.environ["GITHUB_REPOSITORY"],
            os.environ["GH_TOKEN"],
            os.environ["GITHUB_RUN_ID"],
        )
    else:
        base = subprocess.check_output(
            ["git", "merge-base", "HEAD", "origin/main"], text=True
        ).strip()
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"base={base or ''}\n")


if __name__ == "__main__":
    main()
