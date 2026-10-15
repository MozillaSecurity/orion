# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Execute one selected operation from the generated GitHub Actions graph."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

from . import TASKCLUSTER_ROOT_URL, Taskcluster
from .gha_plan import job_id
from .git import GitRepo
from .orion import (
    ServiceHomebrew,
    ServiceMsys,
    Services,
    ServiceTestOnly,
    ToxServiceTest,
)


def _run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, **kwargs)


def _safe_name(name: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in name)


def _archive_name(name: str, arch: str) -> str:
    return f"{name}-{arch}.tar.zst"


def _artifact_name(name: str, arch: str) -> str:
    """Match the reusable workflow's exact upload-artifact name."""
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    return f"orion-build-{name}-{arch}-{attempt}"


def _verify(repo: Path, revision: str, plan: dict[str, Any], selected_id: str) -> None:
    actual = GitRepo.from_existing(repo).head()
    if actual != revision or plan.get("revision") != revision:
        raise ValueError(
            f"Requested revision {revision!r}, plan revision "
            f"{plan.get('revision')!r}, and checkout revision {actual!r} must match"
        )
    selected = plan.get("selected_jobs", [])
    if selected_id not in selected:
        raise ValueError(f"Job {selected_id!r} is not selected by this plan")


def _download_artifact(name: str, destination: Path) -> None:
    run_id = os.environ.get("GITHUB_RUN_ID")
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not run_id or not repository:
        raise RuntimeError("GITHUB_RUN_ID and GITHUB_REPOSITORY are required")
    destination.mkdir(parents=True, exist_ok=True)
    _run(
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
        env={**os.environ, "GH_TOKEN": os.environ.get("GITHUB_TOKEN", "")},
    )


def _download_indexed_image(name: str, arch: str, destination: Path) -> Path:
    """Download an unchanged Orion image through its stable Taskcluster index."""
    index = Taskcluster.get_service("index")
    queue = Taskcluster.get_service("queue")
    route = f"project.fuzzing.orion.{name}.{arch}.master"
    task_id = index.findTask(route)["taskId"]
    url = (
        f"{TASKCLUSTER_ROOT_URL}/api/queue/v1/task/{task_id}/artifacts/"
        f"public/{name}.tar.zst"
    )
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / _archive_name(name, arch)
    request = urllib.request.Request(url, headers={"User-Agent": "orion-gha"})
    with urllib.request.urlopen(request) as response, path.open("wb") as output:
        shutil.copyfileobj(response, output)
    # Resolve the task once more so failures identify an expired indexed artifact.
    queue.task(task_id)
    return path


def _load_archive(path: Path, destination: Path) -> None:
    tar_path = destination / f"{path.stem}.tar"
    _run(["zstd", "-d", "-f", str(path), "-o", str(tar_path)])
    _run(["docker", "load", "--input", str(tar_path)])
    tar_path.unlink()


def _needed_images(
    services: Services, operation: str, name: str, arch: str
) -> set[tuple[str, str]]:
    if operation == "build":
        names = services[name].service_deps
    elif operation == "recipe-test":
        names = services.recipes[name].service_deps
        arch = "amd64"
    else:
        service = services[name]
        names = {
            test.image
            for test in service.tests
            if isinstance(test, ToxServiceTest) and test.image in services
        }
        arch = "amd64"
    return {
        (dependency, arch if arch in services[dependency].archs else "amd64")
        for dependency in names
        if not isinstance(services[dependency], ServiceTestOnly)
    }


def _load_dependencies(
    services: Services,
    operation: str,
    name: str,
    arch: str,
    plan: dict[str, Any],
    runner_temp: Path,
) -> None:
    for dependency, dep_arch in sorted(_needed_images(services, operation, name, arch)):
        selected_id = job_id("build", dependency, dep_arch)
        if selected_id in plan.get("selected_jobs", []):
            artifact = _artifact_name(dependency, dep_arch)
            artifact_dir = runner_temp / "dependencies" / artifact
            _download_artifact(artifact, artifact_dir)
            archive = artifact_dir / _archive_name(dependency, dep_arch)
            if not archive.is_file():
                raise FileNotFoundError(
                    f"Selected dependency {selected_id} did not provide {archive}"
                )
        else:
            archive = _download_indexed_image(
                dependency, dep_arch, runner_temp / "dependencies" / "taskcluster"
            )
        _load_archive(archive, runner_temp)


def _native_build(service: ServiceMsys | ServiceHomebrew, repo: Path) -> Path:
    # Existing setup scripts intentionally run beside an `orion/` checkout.
    work = repo.parent
    service_path = service.root.relative_to(repo).as_posix()
    if isinstance(service, ServiceMsys):
        archive = work / "msys2.tar.xz"
        with (
            urllib.request.urlopen(service.base) as response,
            archive.open("wb") as output,
        ):
            shutil.copyfileobj(response, output)
        _run(["C:/msys64/usr/bin/bsdtar.exe", "-xf", str(archive)], cwd=work)
        bash = work / "msys64" / "usr" / "bin" / "bash.exe"
        env = {
            **os.environ,
            "MSYSTEM": "MINGW64",
            "HOME": str(work),
            "ARTIFACTS": str(work),
            "PATH": ";".join(
                [
                    str(work / "msys64" / "MINGW64" / "bin"),
                    str(work / "msys64" / "usr" / "bin"),
                    os.environ.get("PATH", ""),
                ]
            ),
        }
        _run([str(bash), "-lc", " "], cwd=work, env=env)
        update_script = work / "pacman_upd.bat"
        update_script_body = (
            "@echo off\r\n"
            "bash -c -x -e 'retry () { i=0; while [ $i -lt 9 ]; do "
            'if "$@"; then return; else sleep 30; fi; '
            'i=$((i + 1)); done; "$@"; }; '
            "retry pacman --noconfirm -Syuu'\r\n"
            "exit /b 0\r\n"
        )
        with update_script.open("w", newline="") as output:
            output.write(update_script_body)
        _run(["cmd.exe", "/c", str(update_script)], cwd=work, env=env)
        _run(["cmd.exe", "/c", str(update_script)], cwd=work, env=env)
        _run(
            [str(bash), "-c", f"./orion/{service_path}/setup.sh"],
            cwd=work,
            env=env,
        )
        return work / "msys2.tar.bz2"

    assert isinstance(service, ServiceHomebrew)
    brew_archive = work / "homebrew.tar.gz"
    with (
        urllib.request.urlopen(service.base) as response,
        brew_archive.open("wb") as output,
    ):
        shutil.copyfileobj(response, output)
    homebrew = work / "homebrew"
    homebrew.mkdir()
    _run(
        ["tar", "-xzf", str(brew_archive), "--strip-components=1", "-C", str(homebrew)]
    )
    env = {**os.environ, "HOMEBREW_PREFIX": str(homebrew)}
    _run(
        [
            "bash",
            "-lc",
            f'eval "$({homebrew}/bin/brew shellenv)" && '
            f"./orion/{service_path}/setup.sh",
        ],
        cwd=work,
        env=env,
    )
    return work / "homebrew.tar.bz2"


def prepare(
    repo: Path,
    operation: str,
    name: str,
    arch: str,
    revision: str,
    plan: dict[str, Any],
    *,
    runner_temp: Path | None = None,
) -> dict[str, str]:
    """Validate a selected graph job and prepare native or Docker execution."""
    services = Services(GitRepo.from_existing(repo))
    kind = {
        "recipe-test": "recipe_test",
        "service-test": "service_test",
        "build": "build",
    }[operation]
    selected_id = job_id(kind, name, arch if operation == "build" else None)
    _verify(repo, revision, plan, selected_id)
    temp = runner_temp or Path(os.environ.get("RUNNER_TEMP", "/tmp"))
    temp.mkdir(parents=True, exist_ok=True)
    _load_dependencies(services, operation, name, arch, plan, temp)

    if operation == "service-test":
        return {}
    if operation == "build":
        service = services[name]
        if isinstance(service, (ServiceMsys, ServiceHomebrew)):
            artifact = _native_build(service, repo)
            return {"native_archive": str(artifact)}
        assert service.dockerfile is not None
        image_tar = temp / f"{_safe_name(name)}-{arch}.docker.tar"
        return {
            "build_context": str(services.root),
            "build_file": str(service.dockerfile.relative_to(services.root)),
            "build_tags": f"mozillasecurity/{name}:latest",
            "build_args": "",
            "image_tar": str(image_tar),
        }

    recipe = services.recipes[name]
    default_dockerfile = repo / "services/test-recipes/Dockerfile"
    override = default_dockerfile.with_name(f"Dockerfile-{Path(name).stem}")
    dockerfile = override if override.is_file() else default_dockerfile
    return {
        "build_context": str(repo),
        "build_file": str(dockerfile.relative_to(repo)),
        "build_tags": f"mozillasecurity/test-{Path(name).stem}:latest",
        "build_args": f"recipe={recipe.file.name}",
    }


def run_tests(repo: Path, name: str, revision: str, plan: dict[str, Any]) -> None:
    """Run configured tox tests against the planned image in the checked-out tree."""
    services = Services(GitRepo.from_existing(repo))
    _verify(repo, revision, plan, job_id("service_test", name))
    service = services[name]
    tests = [test for test in service.tests if isinstance(test, ToxServiceTest)]
    if not tests:
        return
    for test in tests:
        image = (
            f"mozillasecurity/{test.image}:latest"
            if test.image in services
            else test.image
        )
        command = [
            "docker",
            "run",
            "--rm",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "-v",
            f"{repo}:/repo",
            "-w",
            "/repo",
            "-e",
            "HOME=/tmp",
            "-e",
            "CI=true",
            "-e",
            "GITHUB_ACTIONS=true",
            "-e",
            "GIT_CONFIG_COUNT=1",
            "-e",
            "GIT_CONFIG_KEY_0=safe.directory",
            "-e",
            "GIT_CONFIG_VALUE_0=/repo",
            image,
            "bash",
            "-lc",
            f"cd '{service.root.relative_to(repo)}' && tox -e '{test.toxenv}'",
        ]
        _run(command)


def finalize(name: str, arch: str, image_tar: Path, digest: str = "") -> Path:
    """Compress a Buildx Docker export into the established Taskcluster artifact."""
    temp = Path(os.environ.get("RUNNER_TEMP", "/tmp"))
    archive = temp / _archive_name(name, arch)
    _run(
        [
            "docker",
            "save",
            "--output",
            str(image_tar),
            f"mozillasecurity/{name}:latest",
        ]
    )
    _run(["zstd", "-T0", "-19", "-f", str(image_tar), "-o", str(archive)])
    image_tar.unlink(missing_ok=True)
    metadata = {"name": name, "arch": arch, "digest": digest}
    (temp / "build.json").write_text(json.dumps(metadata, sort_keys=True) + "\n")
    return archive


def publish_images(
    repo: Path, plan: dict[str, Any], runner_temp: Path | None = None
) -> Path:
    """Push run-specific staging tags, then publish latest by immutable digests."""
    actual = GitRepo.from_existing(repo).head()
    if plan.get("revision") != actual or not plan.get("publish"):
        raise ValueError(
            "Docker publication requires the exact planned publish revision"
        )
    temp = runner_temp or Path(os.environ.get("RUNNER_TEMP", "/tmp"))
    services = Services(GitRepo.from_existing(repo))
    selected = set(plan.get("selected_jobs", []))
    images: dict[str, dict[str, str]] = {}
    for service in services.values():
        if isinstance(service, (ServiceMsys, ServiceHomebrew, ServiceTestOnly)):
            continue
        for arch in service.archs:
            selected_id = job_id("build", service.name, arch)
            if selected_id not in selected:
                continue
            artifact = _artifact_name(service.name, arch)
            artifact_dir = temp / "publish" / artifact
            _download_artifact(artifact, artifact_dir)
            archive = artifact_dir / _archive_name(service.name, arch)
            if not archive.is_file():
                raise FileNotFoundError(
                    f"Selected build {selected_id} did not provide {archive}"
                )
            tar_path = temp / f"{_safe_name(service.name)}-{arch}.tar"
            _run(["zstd", "-d", "-f", str(archive), "-o", str(tar_path)])
            _run(["docker", "load", "--input", str(tar_path)])
            tar_path.unlink()
            revision = plan["revision"]
            run_id = os.environ["GITHUB_RUN_ID"]
            attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
            staging_tag = (
                f"mozillasecurity/{service.name}:gha-"
                f"{revision}-{run_id}-{attempt}-{arch}"
            )
            _run(
                ["docker", "tag", f"mozillasecurity/{service.name}:latest", staging_tag]
            )
            _run(["docker", "push", staging_tag])
            inspect = subprocess.run(
                ["docker", "buildx", "imagetools", "inspect", staging_tag],
                check=True,
                capture_output=True,
                text=True,
            )
            match = re.search(
                r"^Digest:\s+(sha256:[0-9a-f]{64})\s*$", inspect.stdout, re.M
            )
            if not match:
                raise RuntimeError(f"Could not read pushed digest for {staging_tag}")
            images.setdefault(service.name, {})[arch] = match.group(1)
            archive.unlink()
            (artifact_dir / "build.json").unlink(missing_ok=True)
            artifact_dir.rmdir()
            _run(
                [
                    "docker",
                    "image",
                    "rm",
                    staging_tag,
                    f"mozillasecurity/{service.name}:latest",
                ]
            )

    for name, arch_digests in sorted(images.items()):
        service = services[name]
        if set(service.archs) - arch_digests.keys():
            continue
        sources = [
            f"mozillasecurity/{name}@{arch_digests[arch]}"
            for arch in sorted(service.archs)
        ]
        _run(
            [
                "docker",
                "buildx",
                "imagetools",
                "create",
                "--tag",
                f"mozillasecurity/{name}:latest",
                *sources,
            ]
        )
    published = temp / "published-images.json"
    published.write_text(json.dumps(images, sort_keys=True, indent=2) + "\n")
    return published


def reject_stale_publication(repository: str, branch: str, revision: str) -> None:
    """Stop an older queued publication from replacing the current branch head."""
    result = subprocess.run(
        ["gh", "api", f"repos/{repository}/branches/{branch}", "--jq", ".commit.sha"],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "GH_TOKEN": os.environ.get("GITHUB_TOKEN", "")},
    )
    if result.stdout.strip() != revision:
        raise RuntimeError(
            f"Refusing stale publication for {revision}; branch head is "
            f"{result.stdout.strip()}"
        )
    current_run_id = os.environ.get("GITHUB_RUN_ID")
    if not current_run_id:
        raise RuntimeError("GITHUB_RUN_ID is required to publish Orion artifacts")

    latest_run_id = latest_eligible_publication_run_id(repository, branch)
    if latest_run_id is not None and int(current_run_id) < latest_run_id:
        raise RuntimeError(
            f"Refusing publication run {current_run_id}; newer eligible Orion "
            f"workflow run {latest_run_id} exists. Start a new workflow_dispatch "
            "run and select or force the services to publish."
        )


def latest_eligible_publication_run_id(repository: str, branch: str) -> int | None:
    """Find the newest master publication run, excluding unrelated event types."""
    latest: int | None = None
    for event in ("push", "schedule", "workflow_dispatch"):
        page = 1
        while True:
            result = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{repository}/actions/workflows/orion.yml/runs"
                    f"?branch={branch}&event={event}&per_page=100&page={page}",
                ],
                check=True,
                capture_output=True,
                text=True,
                env={**os.environ, "GH_TOKEN": os.environ.get("GITHUB_TOKEN", "")},
            )
            runs = json.loads(result.stdout).get("workflow_runs", [])
            found_event_run = False
            for run in runs:
                path = str(run.get("path", "")).split("@", 1)[0]
                if (
                    run.get("head_branch") == branch
                    and run.get("event") == event
                    and path == ".github/workflows/orion.yml"
                ):
                    run_id = int(run["id"])
                    latest = run_id if latest is None else max(latest, run_id)
                    found_event_run = True
            if found_event_run or len(runs) < 100:
                break
            page += 1
    return latest


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m orion_decision.gha_run")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "run", "finalize", "publish", "check-head"):
        sub = subparsers.add_parser(command)
        if command in {"prepare", "run"}:
            sub.add_argument(
                "--operation",
                choices={"recipe-test", "service-test", "build"},
                required=True,
            )
            sub.add_argument("--name", required=True)
            sub.add_argument("--arch", default="amd64")
            sub.add_argument("--revision", required=True)
            sub.add_argument("--plan-file", type=Path, required=True)
            sub.add_argument("--repo", type=Path, default=Path.cwd())
        elif command == "publish":
            sub.add_argument("--plan-file", type=Path, required=True)
            sub.add_argument("--repo", type=Path, default=Path.cwd())
        elif command == "check-head":
            sub.add_argument("--repository", required=True)
            sub.add_argument("--branch", required=True)
            sub.add_argument("--revision", required=True)
        elif command == "finalize":
            sub.add_argument("--name", required=True)
            sub.add_argument("--arch", default="amd64")
            sub.add_argument("--image-tar", type=Path, required=True)
            sub.add_argument("--digest", default="")
    args = parser.parse_args()
    if args.command == "check-head":
        reject_stale_publication(args.repository, args.branch, args.revision)
        return
    if args.command == "publish":
        publish_images(args.repo, json.loads(args.plan_file.read_text()))
        return
    if args.command == "finalize":
        print(finalize(args.name, args.arch, args.image_tar, args.digest))
        return
    plan = json.loads(args.plan_file.read_text())
    if args.command == "run":
        run_tests(args.repo, args.name, args.revision, plan)
        return
    outputs = prepare(
        args.repo, args.operation, args.name, args.arch, args.revision, plan
    )
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        for key, value in outputs.items():
            output.write(f"{key}={value}\n")


if __name__ == "__main__":
    main()
