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
import sys
import urllib.request
from pathlib import Path
from typing import Any

from . import TASKCLUSTER_ROOT_URL, Taskcluster
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


def _run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, **kwargs)


def _safe_name(name: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in name)


def _archive_name(name: str, arch: str) -> str:
    return f"{name}-{arch}.tar.zst"


def _artifact_name(name: str, arch: str) -> str:
    """Resolve the newest live artifact for this service and architecture."""
    from .gha_publish import _actions_artifacts, select_build_artifact

    run_id = os.environ.get("GITHUB_RUN_ID")
    repository = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    if not run_id or not repository or not token:
        raise RuntimeError("GitHub run identity and token are required for artifacts")
    artifacts = _actions_artifacts(token, repository, run_id)
    selected = select_build_artifact(
        artifacts, name, arch, os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    )
    if selected is None:
        raise FileNotFoundError(
            f"No live build artifact for {name}/{arch} exists in this run "
            "at or before the current attempt"
        )
    return str(selected["name"])


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
    route = f"project.fuzzing.orion.{name}.{arch}.main"
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


def run_tests(
    repo: Path,
    name: str,
    revision: str,
    plan: dict[str, Any],
    *,
    test_index: int | None = None,
) -> None:
    """Run selected service tox checks in the checkout or their configured image."""
    services = Services(GitRepo.from_existing(repo))
    _verify(repo, revision, plan, job_id("service_test", name))
    service = services[name]
    if test_index is not None:
        if test_index < 0 or test_index >= len(service.tests):
            raise ValueError(
                f"Test index {test_index} is outside the tests for service {name!r}"
            )
        selected = service.tests[test_index]
        if not isinstance(selected, ToxServiceTest):
            raise ValueError(f"Test index {test_index} is not a tox test")
        tests = [selected]
    else:
        tests = [test for test in service.tests if isinstance(test, ToxServiceTest)]
        native_versions = {test.python_version for test in tests if test.python_version}
        if len(native_versions) > 1:
            raise ValueError(
                "This service has native tests for multiple Python versions; "
                "select one with --test-index"
            )
    if not tests:
        return
    for test in tests:
        if test.python_version is not None:
            runtime_version = f"{sys.version_info.major}.{sys.version_info.minor}"
            if runtime_version != test.python_version:
                raise RuntimeError(
                    f"Test {test.name!r} requires Python {test.python_version}, "
                    f"but the current runtime is Python {runtime_version}"
                )
            env = os.environ.copy()
            env.setdefault("CI", "true")
            _run(["tox", "-e", test.toxenv], cwd=service.root, env=env)
            continue
        assert test.image is not None, f"Test {test.name!r} needs an image"
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


def _docker_service(repo: GitRepo, plan: dict[str, Any], name: str) -> Service:
    if plan.get("revision") != repo.head() or not plan.get("publish"):
        raise ValueError(
            "Docker publication requires the exact planned publish revision"
        )
    service = Services(repo)[name]
    if isinstance(service, (ServiceMsys, ServiceHomebrew, ServiceTestOnly)):
        raise ValueError(f"{name!r} does not publish Docker images")
    return service


def stage_images(
    repo: Path,
    plan: dict[str, Any],
    name: str,
    runner_temp: Path,
) -> dict[str, str]:
    """Push unique staging tags and return immutable digests for every architecture."""
    service = _docker_service(GitRepo.from_existing(repo), plan, name)
    selected = set(plan["selected_jobs"])
    results = json.loads(os.environ["ORION_JOB_RESULTS"])
    digests: dict[str, str] = {}
    for arch in sorted(service.archs):
        build = job_id("build", name, arch)
        if build not in selected or results.get(build, {}).get("result") != "success":
            raise ValueError(
                f"Cannot stage Docker image without successful build {build}"
            )

        artifact = _artifact_name(name, arch)
        artifact_dir = runner_temp / "publish" / artifact
        _download_artifact(artifact, artifact_dir)
        archive = artifact_dir / _archive_name(name, arch)
        if not archive.is_file():
            raise FileNotFoundError(f"Selected build {build} did not provide {archive}")
        tar_path = archive.with_suffix("")
        _run(["zstd", "-d", "-f", str(archive), "-o", str(tar_path)])

        staging_tag = (
            f"mozillasecurity/{name}:gha-{plan['revision']}-"
            f"{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}-{arch}"
        )
        # Buildx requires OCI manifests to create an index with annotations.
        digest_file = artifact_dir / "pushed-digest"
        _run(
            [
                "skopeo",
                "copy",
                "--format",
                "oci",
                "--digestfile",
                str(digest_file),
                f"docker-archive:{tar_path}",
                f"docker://{staging_tag}",
            ]
        )
        digest = digest_file.read_text().strip()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise RuntimeError(f"Could not read pushed digest for {staging_tag}")
        digests[arch] = digest
        shutil.rmtree(artifact_dir)
    return digests


_DOCKER_ANNOTATION = "org.mozilla.orion."


def _latest_image_annotations(name: str) -> dict[str, str]:
    """Read the current Docker index while holding the service promotion lock."""
    inspect = subprocess.run(
        [
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            "--raw",
            f"mozillasecurity/{name}:latest",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if inspect.returncode:
        missing_reference = re.search(
            rf"(?:^|\s)(?:docker\.io/)?mozillasecurity/"
            rf"{re.escape(name)}:latest: not found(?:$|\s)",
            inspect.stderr,
            re.IGNORECASE,
        )
        if missing_reference or re.search(
            r"manifest unknown|no such manifest", inspect.stderr, re.IGNORECASE
        ):
            return {}
        raise RuntimeError(
            f"Could not inspect latest manifest for {name}: {inspect.stderr.strip()}"
        )
    return json.loads(inspect.stdout).get("annotations", {})


def _legacy_docker_run(run_id: str) -> dict[str, Any]:
    from .gha_publish import _github_json

    run = _github_json(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}"
        f"/actions/runs/{run_id}",
        token=os.environ["GITHUB_TOKEN"],
    )
    if (
        run["path"].split("@", 1)[0] != ".github/workflows/orion.yml"
        or run["head_branch"] != "main"
        or run["event"] not in {"push", "schedule", "workflow_dispatch"}
    ):
        raise ValueError(f"Docker latest references unexpected GitHub run {run_id}")
    return run


def _latest_image_order(
    annotations: dict[str, str], main_positions: dict[str, int]
) -> tuple[int, int, int]:
    from .gha_publish import publication_order

    provenance = {
        key.removeprefix(_DOCKER_ANNOTATION): value
        for key, value in annotations.items()
        if key.startswith(_DOCKER_ANNOTATION)
    }
    if not provenance:
        # Images published before Orion annotated manifests are superseded by a
        # successful current publication.
        return (0, 0, 0)
    run_id = provenance["github-run-id"]
    attempt = provenance["github-run-attempt"]
    if "revision" not in provenance and "github-run-number" not in provenance:
        run = _legacy_docker_run(run_id)
        revision = run["head_sha"]
        run_number = run["run_number"]
    else:
        revision = provenance["revision"]
        run_number = provenance["github-run-number"]
    return publication_order(main_positions[revision], run_number, attempt)


def promote_images(
    repo_path: Path,
    plan: dict[str, Any],
    name: str,
    digests: dict[str, str],
    runner_temp: Path,
) -> Path:
    """Promote exact staged images under the per-service GitHub concurrency lock."""
    from .gha_publish import main_positions, publication_order

    repo = GitRepo.from_existing(repo_path)
    service = _docker_service(repo, plan, name)
    if set(digests) != set(service.archs) or any(
        not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) for digest in digests.values()
    ):
        raise ValueError(f"Staging did not provide all valid digests for {name}")
    positions = main_positions(repo)
    revision = plan["revision"]
    landing_order = positions.get(revision)
    if landing_order is None or landing_order != plan["landing_order"]:
        raise ValueError(
            f"Planned revision {revision} is not at its expected position on main"
        )
    run_number = os.environ["GITHUB_RUN_NUMBER"]
    attempt = os.environ["GITHUB_RUN_ATTEMPT"]
    order = publication_order(landing_order, run_number, attempt)
    publication: dict[str, Any] = {"architectures": digests, "latest_published": False}
    output = runner_temp / "published-images.json"
    try:
        latest_order = _latest_image_order(_latest_image_annotations(name), positions)
        if latest_order > order:
            print(f"Docker latest for {name} already has a newer publication")
            publication["superseded"] = True
        else:
            annotations = {
                "revision": revision,
                "github-run-id": os.environ["GITHUB_RUN_ID"],
                "github-run-number": run_number,
                "github-run-attempt": attempt,
            }
            command = [
                "docker",
                "buildx",
                "imagetools",
                "create",
                "--tag",
                f"mozillasecurity/{name}:latest",
            ]
            for key, value in annotations.items():
                command.extend(
                    ["--annotation", f"index:{_DOCKER_ANNOTATION}{key}={value}"]
                )
            command.extend(
                f"mozillasecurity/{name}@{digests[arch]}" for arch in sorted(digests)
            )
            _run(command)
            publication["latest_published"] = True
    finally:
        output.write_text(
            json.dumps({name: publication}, sort_keys=True, indent=2) + "\n"
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m orion_decision.gha_run")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "run", "finalize", "stage", "promote"):
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
            if command == "run":
                sub.add_argument("--test-index", type=int)
        elif command in {"stage", "promote"}:
            sub.add_argument("--plan-file", type=Path, required=True)
            sub.add_argument("--repo", type=Path, default=Path.cwd())
            sub.add_argument("--service", required=True)
        elif command == "finalize":
            sub.add_argument("--name", required=True)
            sub.add_argument("--arch", default="amd64")
            sub.add_argument("--image-tar", type=Path, required=True)
            sub.add_argument("--digest", default="")
    args = parser.parse_args()
    if args.command in {"stage", "promote"}:
        plan = json.loads(args.plan_file.read_text())
        runner_temp = Path(os.environ["RUNNER_TEMP"])
        if args.command == "stage":
            digests = stage_images(args.repo, plan, args.service, runner_temp)
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
                output.write(f"digests={json.dumps(digests)}\n")
        else:
            promote_images(
                args.repo,
                plan,
                args.service,
                json.loads(os.environ["ORION_STAGED_DIGESTS"]),
                runner_temp,
            )
        return
    if args.command == "finalize":
        print(finalize(args.name, args.arch, args.image_tar, args.digest))
        return
    plan = json.loads(args.plan_file.read_text())
    if args.command == "run":
        run_tests(
            args.repo,
            args.name,
            args.revision,
            plan,
            test_index=args.test_index,
        )
        return
    outputs = prepare(
        args.repo, args.operation, args.name, args.arch, args.revision, plan
    )
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        for key, value in outputs.items():
            output.write(f"{key}={value}\n")


if __name__ == "__main__":
    main()
