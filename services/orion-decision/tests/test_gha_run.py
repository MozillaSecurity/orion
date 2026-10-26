# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Focused tests for GitHub Actions operation execution."""

import io
import json
import os
import signal
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from yaml import safe_load

from orion_decision import gha_run
from orion_decision.gha_plan import job_id

REPO_ROOT = Path(__file__).resolve().parents[3]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def make_repo(root: Path, files: dict[str, str]) -> tuple[Path, str]:
    root.mkdir()
    git(root, "init", "-b", "master")
    git(root, "config", "user.name", "Orion tests")
    git(root, "config", "user.email", "orion-tests@example.invalid")
    for name, contents in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    git(root, "add", "-A")
    git(root, "commit", "-m", "test graph")
    return root, git(root, "rev-parse", "HEAD")


def docker_repo(root: Path) -> tuple[Path, str]:
    return make_repo(
        root,
        {
            "services/base/service.yaml": "name: base\ntests: []\n",
            "services/base/Dockerfile": "FROM alpine:3.20\n",
            "services/consumer/service.yaml": (
                "name: consumer\nforce_deps: [base]\ntests: []\n"
            ),
            "services/consumer/Dockerfile": "FROM alpine:3.20\n",
            "recipes/demo.sh": "#!/bin/sh\n# /force-deps=base\necho demo\n",
            "services/test-recipes/Dockerfile": "FROM ubuntu:24.04\n",
            "services/test-recipes/launch.sh": "#!/bin/sh\nexit 0\n",
            "recipes/linux/common.sh": "#!/bin/sh\n",
        },
    )


def plan(revision: str, *selected: str) -> dict[str, Any]:
    return {"revision": revision, "selected_jobs": list(selected)}


def patch_archive_io(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gha_run, "_load_archive", lambda _archive, _destination: None)
    monkeypatch.setattr(gha_run, "_run", lambda *_args, **_kwargs: None)

    def download_indexed(name: str, arch: str, destination: Path) -> Path:
        archive = destination / f"{name}-{arch}.tar.zst"
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.touch()
        return archive

    monkeypatch.setattr(gha_run, "_download_indexed_image", download_indexed)


def test_selected_dependency_uses_current_run_archive(tmp_path, monkeypatch) -> None:
    """Use this workflow's artifact for a dependency selected in the current run."""
    repo, revision = docker_repo(tmp_path / "repo")
    patch_archive_io(monkeypatch)
    current_run: list[tuple[str, Path]] = []
    indexed: list[tuple[str, str, Path]] = []

    def download_artifact(name: str, destination: Path) -> None:
        current_run.append((name, destination))
        destination.mkdir(parents=True)
        (destination / "base-amd64.tar.zst").touch()

    monkeypatch.setattr(gha_run, "_download_artifact", download_artifact)
    monkeypatch.setattr(
        gha_run,
        "_download_indexed_image",
        lambda name, arch, dest: indexed.append((name, arch, dest)),
    )

    gha_run.prepare(
        repo,
        "build",
        "consumer",
        "amd64",
        revision,
        plan(
            revision,
            job_id("build", "consumer", "amd64"),
            job_id("build", "base", "amd64"),
        ),
        runner_temp=tmp_path / "runner",
    )

    assert current_run == [
        (
            "orion-build-base-amd64-1",
            tmp_path / "runner/dependencies/orion-build-base-amd64-1",
        )
    ]
    assert indexed == []


def test_unchanged_dependency_uses_indexed_archive(tmp_path, monkeypatch) -> None:
    """Use the indexed archive for a dependency unchanged in the current run."""
    repo, revision = docker_repo(tmp_path / "repo")
    patch_archive_io(monkeypatch)
    indexed: list[tuple[str, str, Path]] = []
    monkeypatch.setattr(
        gha_run,
        "_download_artifact",
        lambda *_args: pytest.fail("an unchanged dependency has no current artifact"),
    )

    def download_indexed(name: str, arch: str, destination: Path) -> Path:
        indexed.append((name, arch, destination))
        archive = destination / "base-amd64.tar.zst"
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.touch()
        return archive

    monkeypatch.setattr(gha_run, "_download_indexed_image", download_indexed)
    gha_run.prepare(
        repo,
        "build",
        "consumer",
        "amd64",
        revision,
        plan(revision, job_id("build", "consumer", "amd64")),
        runner_temp=tmp_path / "runner",
    )

    assert indexed == [("base", "amd64", tmp_path / "runner/dependencies/taskcluster")]


def test_missing_selected_dependency_fails_without_index_fallback(
    tmp_path, monkeypatch
) -> None:
    """Fail on a missing selected artifact instead of using an old index."""
    repo, revision = docker_repo(tmp_path / "repo")
    patch_archive_io(monkeypatch)
    monkeypatch.setattr(gha_run, "_download_artifact", lambda *_args: None)
    monkeypatch.setattr(
        gha_run,
        "_download_indexed_image",
        lambda *_args: pytest.fail("selected dependency must not fall back to index"),
    )

    with pytest.raises(FileNotFoundError, match="Selected dependency build_base_amd64"):
        gha_run.prepare(
            repo,
            "build",
            "consumer",
            "amd64",
            revision,
            plan(
                revision,
                job_id("build", "consumer", "amd64"),
                job_id("build", "base", "amd64"),
            ),
            runner_temp=tmp_path / "runner",
        )


def test_dependency_artifact_name_preserves_service_punctuation(tmp_path, monkeypatch):
    """Preserve service name punctuation in dependency artifact names."""
    dependency = "base.service"
    repo, revision = make_repo(
        tmp_path / "repo",
        {
            f"services/{dependency}/service.yaml": f"name: {dependency}\ntests: []\n",
            f"services/{dependency}/Dockerfile": "FROM alpine:3.20\n",
            "services/consumer/service.yaml": (
                f"name: consumer\nforce_deps: [{dependency}]\ntests: []\n"
            ),
            "services/consumer/Dockerfile": "FROM alpine:3.20\n",
        },
    )
    patch_archive_io(monkeypatch)
    artifact_names: list[str] = []

    def download(name: str, destination: Path) -> None:
        artifact_names.append(name)
        destination.mkdir(parents=True)
        (destination / f"{dependency}-amd64.tar.zst").touch()

    monkeypatch.setattr(gha_run, "_download_artifact", download)
    gha_run.prepare(
        repo,
        "build",
        "consumer",
        "amd64",
        revision,
        plan(
            revision,
            job_id("build", "consumer", "amd64"),
            job_id("build", dependency, "amd64"),
        ),
        runner_temp=tmp_path / "runner",
    )

    assert artifact_names == ["orion-build-base.service-amd64-1"]


def test_prepare_rejects_revision_mismatch_before_dependency_io(tmp_path, monkeypatch):
    """Reject a plan for another revision before downloading dependency images."""
    repo, revision = docker_repo(tmp_path / "repo")
    monkeypatch.setattr(
        gha_run,
        "_download_artifact",
        lambda *_args: pytest.fail("revision validation must happen first"),
    )

    with pytest.raises(ValueError, match="must match"):
        gha_run.prepare(
            repo,
            "build",
            "consumer",
            "amd64",
            "0" * 40,
            plan(revision, job_id("build", "consumer", "amd64")),
            runner_temp=tmp_path / "runner",
        )


def test_recipe_test_uses_stem_override_and_recipe_build_arg(tmp_path, monkeypatch):
    """Build recipe tests with the stem override and configured build argument."""
    repo, revision = docker_repo(tmp_path / "repo")
    override = repo / "services/test-recipes/Dockerfile-demo"
    override.write_text("FROM ubuntu:24.04\nARG recipe\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "add recipe override")
    revision = git(repo, "rev-parse", "HEAD")
    patch_archive_io(monkeypatch)

    result = gha_run.prepare(
        repo,
        "recipe-test",
        "demo.sh",
        "amd64",
        revision,
        plan(revision, job_id("recipe_test", "demo.sh")),
        runner_temp=tmp_path / "runner",
    )

    context = Path(result["build_context"])
    build_file = Path(result["build_file"])
    if not build_file.is_absolute():
        build_file = context / build_file
    assert context == repo
    assert build_file.resolve() == override.resolve()
    assert result["build_tags"] == "mozillasecurity/test-demo:latest"
    assert result["build_args"] == "recipe=demo.sh"


def test_service_tox_tests_use_each_service_root_and_environment(tmp_path, monkeypatch):
    """Run each service's tox checks from its own root and configured environment."""
    repo, revision = make_repo(
        tmp_path / "repo",
        {
            "services/alpha/service.yaml": (
                "name: alpha\ntests:\n  - name: lint\n    type: tox\n"
                "    image: python:3.13\n    toxenv: lint\n"
            ),
            "services/alpha/Dockerfile": "FROM alpine:3.20\n",
            "services/beta/service.yaml": (
                "name: beta\ntests:\n  - name: py\n    type: tox\n"
                "    image: python:3.12\n    toxenv: py312\n"
            ),
            "services/beta/Dockerfile": "FROM alpine:3.20\n",
        },
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(
        gha_run, "_run", lambda command, **_kwargs: commands.append(command)
    )

    for name, tox_env, image in (
        ("alpha", "lint", "python:3.13"),
        ("beta", "py312", "python:3.12"),
    ):
        gha_run.run_tests(
            repo,
            name,
            revision,
            plan(revision, job_id("service_test", name)),
        )
        assert commands[-1][-1] == (f"cd 'services/{name}' && tox -e '{tox_env}'")
        assert commands[-1][commands[-1].index("-w") + 1] == "/repo"
        assert image in commands[-1]
        assert commands[-1][commands[-1].index("--user") + 1] == (
            f"{os.getuid()}:{os.getgid()}"
        )
        assert "HOME=/tmp" in commands[-1]
        assert any("safe.directory" in value for value in commands[-1])

    assert len(commands) == 2


def test_finalize_keeps_architecture_archive_name_and_build_metadata(
    tmp_path, monkeypatch
):
    """Finalize images with their architecture-specific archive names and metadata."""
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    commands: list[list[str]] = []
    image = tmp_path / "image.tar"

    def run(command: list[str], **_kwargs: Any) -> None:
        commands.append(command)
        if command[:2] == ["docker", "save"]:
            image.touch()
        elif command[0] == "zstd":
            assert image.is_file()

    monkeypatch.setattr(gha_run, "_run", run)

    archive = gha_run.finalize("fuzzilli", "arm64", image, "sha256:deadbeef")

    assert archive == tmp_path / "fuzzilli-arm64.tar.zst"
    assert commands == [
        [
            "docker",
            "save",
            "--output",
            str(image),
            "mozillasecurity/fuzzilli:latest",
        ],
        ["zstd", "-T0", "-19", "-f", str(image), "-o", str(archive)],
    ]
    assert not image.exists()
    assert json.loads((tmp_path / "build.json").read_text()) == {
        "name": "fuzzilli",
        "arch": "arm64",
        "digest": "sha256:deadbeef",
    }


def test_failed_docker_save_stops_before_compression_or_metadata(tmp_path, monkeypatch):
    """Stop after Docker save fails without compressing or writing metadata."""
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: Any) -> None:
        commands.append(command)
        if command[:2] == ["docker", "save"]:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(gha_run, "_run", run)

    with pytest.raises(subprocess.CalledProcessError):
        gha_run.finalize("fuzzilli", "amd64", tmp_path / "image.tar")

    assert len(commands) == 1 and commands[0][:2] == ["docker", "save"]
    assert not (tmp_path / "build.json").exists()


@pytest.mark.parametrize(
    ("kind", "expected_archive", "expected_setup_fragment"),
    [
        ("msys", "msys2.tar.bz2", "./orion/services/win/setup.sh"),
        ("homebrew", "homebrew.tar.bz2", "./orion/services/brew/setup.sh"),
    ],
)
def test_native_preparation_runs_checked_out_setup_without_rewriting_it(
    tmp_path, monkeypatch, kind, expected_archive, expected_setup_fragment
):
    """Run checked-out native setup scripts without modifying their contents."""
    setup = "#!/bin/sh\necho keep-this-setup\n"
    if kind == "msys":
        metadata = "name: win\ntype: msys\nbase: https://example.invalid/msys.tar.xz\n"
        service_name = "win"
    else:
        metadata = (
            "name: brew\ntype: homebrew\n"
            "base: https://example.invalid/homebrew.tar.gz\n"
        )
        service_name = "brew"
    repo, revision = make_repo(
        tmp_path / "orion",
        {
            f"services/{service_name}/service.yaml": metadata,
            f"services/{service_name}/setup.sh": setup,
        },
    )
    commands: list[tuple[list[str], dict[str, Any]]] = []
    monkeypatch.setattr(
        gha_run,
        "_run",
        lambda command, **kwargs: commands.append((command, kwargs)),
    )
    monkeypatch.setattr(
        gha_run.urllib.request,
        "urlopen",
        lambda _url: io.BytesIO(b"fixture"),
    )

    result = gha_run.prepare(
        repo,
        "build",
        service_name,
        "amd64",
        revision,
        plan(revision, job_id("build", service_name, "amd64")),
        runner_temp=tmp_path / "runner",
    )

    assert result["native_archive"].endswith(expected_archive)
    assert (repo / f"services/{service_name}/setup.sh").read_text() == setup
    command_text = "\n".join(" ".join(command) for command, _ in commands)
    assert expected_setup_fragment in command_text
    if kind == "msys":
        assert any(
            command[:2] == ["C:/msys64/usr/bin/bsdtar.exe", "-xf"]
            for command, _ in commands
        )
        assert sum(command[:2] == ["cmd.exe", "/c"] for command, _ in commands) == 2
        bash_commands = [command for command, _ in commands if "bash.exe" in command[0]]
        assert any(
            any(arg.startswith("-l") for arg in command) for command in bash_commands
        )
        assert any(
            "-c" in command and expected_setup_fragment in " ".join(command)
            for command in bash_commands
        )
        envs = [kwargs.get("env", {}) for _, kwargs in commands]
        setup_env = next(env for env in envs if env.get("MSYSTEM") == "MINGW64")
        assert setup_env["HOME"]
        assert setup_env["ARTIFACTS"]
        assert "msys64/MINGW64/bin" in setup_env["PATH"]
        assert "msys64/usr/bin" in setup_env["PATH"]
        setup_index = next(
            index
            for index, (command, _) in enumerate(commands)
            if expected_setup_fragment in " ".join(command)
        )
        updates = [
            index
            for index, (command, _) in enumerate(commands)
            if command[:2] == ["cmd.exe", "/c"]
        ]
        assert len(updates) == 2 and max(updates) < setup_index
    else:
        assert "shellenv" in command_text
        assert command_text.index("shellenv") < command_text.index(
            expected_setup_fragment
        )
        envs = [kwargs.get("env", {}) for _, kwargs in commands]
        setup_env = next(env for env in envs if "HOMEBREW_PREFIX" in env)
        assert Path(setup_env["HOMEBREW_PREFIX"]).name == "homebrew"


def test_publication_stages_unique_tags_and_builds_manifest_from_exact_digests(
    tmp_path, monkeypatch
):
    """Publish images under unique tags and build the manifest from their digests."""
    repo, revision = make_repo(
        tmp_path / "repo",
        {
            "services/multi/service.yaml": "name: multi\narch: [amd64, arm64]\n",
            "services/multi/Dockerfile": "FROM alpine:3.20\n",
        },
    )
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    commands: list[list[str]] = []
    digests = iter(("a" * 64, "b" * 64))

    def download_artifact(name: str, destination: Path) -> None:
        destination.mkdir(parents=True)
        (destination / f"multi-{name.rsplit('-', 2)[-2]}.tar.zst").touch()

    def run(command: list[str], **_kwargs: Any) -> None:
        commands.append(command)
        if command[0] == "zstd":
            Path(command[command.index("-o") + 1]).touch()

    monkeypatch.setattr(gha_run, "_download_artifact", download_artifact)
    monkeypatch.setattr(gha_run, "_run", run)
    monkeypatch.setattr(
        gha_run.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout=f"Digest: sha256:{next(digests)}\n"
        ),
    )

    gha_run.publish_images(
        repo,
        {
            "revision": revision,
            "publish": True,
            "selected_jobs": [
                job_id("build", "multi", "amd64"),
                job_id("build", "multi", "arm64"),
            ],
        },
        runner_temp=tmp_path / "runner",
    )

    pushed = [command[-1] for command in commands if command[:2] == ["docker", "push"]]
    assert pushed == [
        f"mozillasecurity/multi:gha-{revision}-12345-2-amd64",
        f"mozillasecurity/multi:gha-{revision}-12345-2-arm64",
    ]
    manifest = next(
        command
        for command in commands
        if command[:4] == ["docker", "buildx", "imagetools", "create"]
    )
    assert manifest == [
        "docker",
        "buildx",
        "imagetools",
        "create",
        "--tag",
        "mozillasecurity/multi:latest",
        f"mozillasecurity/multi@sha256:{'a' * 64}",
        f"mozillasecurity/multi@sha256:{'b' * 64}",
    ]


def test_docker_publication_keeps_successful_services_independent(
    tmp_path, monkeypatch
) -> None:
    """Publish a complete image branch when a peer image lacks one architecture."""
    repo, revision = make_repo(
        tmp_path / "repo",
        {
            "services/partial/service.yaml": "name: partial\narch: [amd64, arm64]\n",
            "services/partial/Dockerfile": "FROM alpine:3.20\n",
            "services/complete/service.yaml": "name: complete\narch: [amd64]\n",
            "services/complete/Dockerfile": "FROM alpine:3.20\n",
        },
    )
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv(
        "ORION_JOB_RESULTS",
        json.dumps(
            {
                job_id("build", "partial", "amd64"): {"result": "success"},
                job_id("build", "partial", "arm64"): {"result": "failure"},
                job_id("build", "complete", "amd64"): {"result": "success"},
            }
        ),
    )
    commands: list[list[str]] = []

    def download_artifact(name: str, destination: Path) -> None:
        destination.mkdir(parents=True)
        service, arch = name.removeprefix("orion-build-").rsplit("-", 2)[:2]
        (destination / f"{service}-{arch}.tar.zst").touch()

    def run(command: list[str], **_kwargs: Any) -> None:
        commands.append(command)
        if command[0] == "zstd":
            Path(command[command.index("-o") + 1]).touch()

    monkeypatch.setattr(gha_run, "_download_artifact", download_artifact)
    monkeypatch.setattr(gha_run, "_run", run)
    monkeypatch.setattr(
        gha_run.subprocess,
        "run",
        lambda command, **_kwargs: SimpleNamespace(
            stdout=(
                "Digest: sha256:"
                + ("b" if "complete" in command[-1] else "a") * 64
                + "\n"
            )
        ),
    )

    published = gha_run.publish_images(
        repo,
        {
            "revision": revision,
            "publish": True,
            "selected_jobs": [
                job_id("build", "partial", "amd64"),
                job_id("build", "partial", "arm64"),
                job_id("build", "complete", "amd64"),
            ],
        },
        runner_temp=tmp_path / "runner",
    )

    latest_manifests = [
        command
        for command in commands
        if command[:4] == ["docker", "buildx", "imagetools", "create"]
    ]
    assert [command[5] for command in latest_manifests] == [
        "mozillasecurity/complete:latest"
    ]
    assert json.loads(published.read_text()) == {
        "complete": {
            "architectures": {"amd64": "sha256:" + "b" * 64},
            "latest_published": True,
        },
        "partial": {
            "architectures": {"amd64": "sha256:" + "a" * 64},
            "latest_published": False,
        },
    }


def test_docker_manifest_failure_does_not_block_a_peer_service(
    tmp_path, monkeypatch
) -> None:
    """Continue publishing peer images after one service's latest tag fails."""
    repo, revision = make_repo(
        tmp_path / "repo",
        {
            "services/broken/service.yaml": "name: broken\narch: [amd64]\n",
            "services/broken/Dockerfile": "FROM alpine:3.20\n",
            "services/healthy/service.yaml": "name: healthy\narch: [amd64]\n",
            "services/healthy/Dockerfile": "FROM alpine:3.20\n",
        },
    )
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv(
        "ORION_JOB_RESULTS",
        json.dumps(
            {
                job_id("build", "broken", "amd64"): {"result": "success"},
                job_id("build", "healthy", "amd64"): {"result": "success"},
            }
        ),
    )
    commands: list[list[str]] = []

    def download_artifact(name: str, destination: Path) -> None:
        service = name.removeprefix("orion-build-").removesuffix("-amd64-1")
        destination.mkdir(parents=True)
        (destination / f"{service}-amd64.tar.zst").touch()

    def run(command: list[str], **_kwargs: Any) -> None:
        commands.append(command)
        if command[0] == "zstd":
            Path(command[command.index("-o") + 1]).touch()
        if (
            command[:4] == ["docker", "buildx", "imagetools", "create"]
            and command[5] == "mozillasecurity/broken:latest"
        ):
            raise RuntimeError("Docker Hub rejected broken:latest")

    monkeypatch.setattr(gha_run, "_download_artifact", download_artifact)
    monkeypatch.setattr(gha_run, "_run", run)
    monkeypatch.setattr(
        gha_run.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="Digest: sha256:" + "c" * 64 + "\n"
        ),
    )
    runner_temp = tmp_path / "runner"

    with pytest.raises(RuntimeError, match="broken/latest"):
        gha_run.publish_images(
            repo,
            {
                "revision": revision,
                "publish": True,
                "selected_jobs": [
                    job_id("build", "broken", "amd64"),
                    job_id("build", "healthy", "amd64"),
                ],
            },
            runner_temp=runner_temp,
        )

    assert any(
        command[:4] == ["docker", "buildx", "imagetools", "create"]
        and command[5] == "mozillasecurity/healthy:latest"
        for command in commands
    )
    assert (runner_temp / "published-images.json").is_file()


def test_scoped_publication_does_not_consume_peer_builds_or_failures(
    tmp_path, monkeypatch
):
    """Limit a service publication to its own archives and latest manifest."""
    repo, revision = make_repo(
        tmp_path / "repo",
        {
            "services/target/service.yaml": "name: target\narch: [amd64]\n",
            "services/target/Dockerfile": "FROM alpine:3.20\n",
            "services/peer/service.yaml": "name: peer\narch: [amd64]\n",
            "services/peer/Dockerfile": "FROM alpine:3.20\n",
        },
    )
    monkeypatch.setenv("GITHUB_RUN_ID", "100")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv(
        "ORION_JOB_RESULTS",
        json.dumps(
            {
                job_id("build", "target", "amd64"): {"result": "success"},
                job_id("build", "peer", "amd64"): {"result": "failure"},
            }
        ),
    )
    downloads: list[str] = []
    commands: list[list[str]] = []

    def download(name: str, destination: Path) -> None:
        downloads.append(name)
        destination.mkdir(parents=True)
        (destination / "target-amd64.tar.zst").touch()

    def run(command: list[str], **_kwargs: Any) -> None:
        commands.append(command)
        if command[0] == "zstd":
            Path(command[command.index("-o") + 1]).touch()

    monkeypatch.setattr(gha_run, "_download_artifact", download)
    monkeypatch.setattr(gha_run, "_run", run)
    monkeypatch.setattr(
        gha_run, "_has_newer_successful_service_publication", lambda *_: False
    )
    monkeypatch.setattr(
        gha_run.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="Digest: sha256:" + "d" * 64 + "\n"
        ),
    )

    output = gha_run.publish_images(
        repo,
        {
            "revision": revision,
            "publish": True,
            "selected_jobs": [
                job_id("build", "target", "amd64"),
                job_id("build", "peer", "amd64"),
            ],
        },
        runner_temp=tmp_path / "runner",
        service_name="target",
    )

    assert downloads == ["orion-build-target-amd64-1"]
    latest = [
        c for c in commands if c[:4] == ["docker", "buildx", "imagetools", "create"]
    ]
    assert [c[5] for c in latest] == ["mozillasecurity/target:latest"]
    assert latest[0][6:10] == [
        "--annotation",
        "index:org.mozilla.orion.github-run-id=100",
        "--annotation",
        "index:org.mozilla.orion.github-run-attempt=1",
    ]
    assert json.loads(output.read_text()) == {
        "target": {
            "architectures": {"amd64": "sha256:" + "d" * 64},
            "latest_published": True,
        }
    }


@pytest.mark.parametrize(
    ("returncode", "raw", "stderr", "expected", "raises"),
    [
        (
            0,
            {
                "annotations": {
                    "org.mozilla.orion.github-run-id": "200",
                    "org.mozilla.orion.github-run-attempt": "1",
                }
            },
            "",
            True,
            False,
        ),
        (
            0,
            {
                "annotations": {
                    "org.mozilla.orion.github-run-id": "100",
                    "org.mozilla.orion.github-run-attempt": "1",
                }
            },
            "",
            False,
            False,
        ),
        (0, {"annotations": {}}, "", False, False),
        (1, {}, "manifest unknown", False, False),
        (
            1,
            {},
            "ERROR: docker.io/mozillasecurity/target:latest: not found",
            False,
            False,
        ),
        (
            1,
            {},
            "ERROR: docker.io/mozillasecurity/peer:latest: not found",
            False,
            True,
        ),
        (1, {}, "unauthorized", False, True),
    ],
)
def test_service_latest_freshness_uses_durable_index_annotations(
    monkeypatch, returncode, raw, stderr, expected, raises
):
    """Compare index run attempts and fail closed on inspect errors."""
    monkeypatch.setenv("GITHUB_RUN_ID", "100")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    result = SimpleNamespace(
        returncode=returncode,
        stdout=json.dumps(raw),
        stderr=stderr,
    )
    commands: list[list[str]] = []

    def inspect(command, **_kwargs):
        commands.append(command)
        return result

    monkeypatch.setattr(gha_run.subprocess, "run", inspect)
    if raises:
        with pytest.raises(RuntimeError, match="Could not inspect latest manifest"):
            gha_run._has_newer_successful_service_publication("target")
    else:
        assert gha_run._has_newer_successful_service_publication("target") is expected
    assert commands == [
        [
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            "--raw",
            "mozillasecurity/target:latest",
        ]
    ]


def test_stale_publication_is_rejected_against_current_branch_head(monkeypatch):
    """Reject publication when the workflow revision is no longer the branch head."""
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.setattr(
        gha_run.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="newer-revision\n"),
    )

    with pytest.raises(RuntimeError, match="Refusing stale publication"):
        gha_run.reject_stale_publication("org/orion", "master", "older-revision")


def test_same_sha_older_workflow_run_is_rejected(monkeypatch):
    """Reject an older workflow run when a newer run targets the same revision."""
    monkeypatch.setenv("GITHUB_RUN_ID", "100")
    responses = [
        SimpleNamespace(stdout="same-revision\n"),
        SimpleNamespace(
            stdout=json.dumps(
                {
                    "workflow_runs": [
                        {
                            "id": 200,
                            "path": ".github/workflows/orion.yml@refs/heads/master",
                            "head_branch": "master",
                            "event": "push",
                        },
                        {
                            "id": 999,
                            "path": ".github/workflows/orion.yml@refs/pull/1/merge",
                            "head_branch": "master",
                            "event": "pull_request",
                        },
                    ]
                }
            )
        ),
        SimpleNamespace(stdout=json.dumps({"workflow_runs": []})),
        SimpleNamespace(stdout=json.dumps({"workflow_runs": []})),
    ]
    calls: list[list[str]] = []

    def run(command, **_kwargs):
        calls.append(command)
        return responses.pop(0)

    monkeypatch.setattr(gha_run.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="Start a new workflow_dispatch run"):
        gha_run.reject_stale_publication("org/orion", "master", "same-revision")
    assert len(calls) == 4
    assert all("actions/workflows/orion.yml/runs" in call[-1] for call in calls[1:])


def test_latest_eligible_run_paginates_until_it_finds_exact_workflow(monkeypatch):
    """Search pages until the latest eligible run matches the exact workflow."""
    pages = [
        {"workflow_runs": [{"id": 1, "path": ".github/workflows/other.yml"}] * 100},
        {
            "workflow_runs": [
                {
                    "id": 250,
                    "path": ".github/workflows/orion.yml@refs/heads/master",
                    "head_branch": "master",
                    "event": "push",
                },
                {
                    "id": 275,
                    "path": ".github/workflows/orion.yml@refs/heads/master",
                    "head_branch": "master",
                    "event": "push",
                },
            ]
        },
        {"workflow_runs": []},
        {"workflow_runs": []},
    ]
    calls: list[list[str]] = []

    def run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(stdout=json.dumps(pages.pop(0)))

    monkeypatch.setattr(gha_run.subprocess, "run", run)
    assert gha_run.latest_eligible_publication_run_id("org/orion", "master") == 275
    assert "page=2" in calls[1][-1]


@pytest.mark.parametrize(
    ("signal_name", "expected_marker", "expected_exit"),
    [("USR1", "int", 0), ("TERM", "term", 143)],
)
def test_worker_wrapper_forwards_drain_and_cancel_signals(
    tmp_path, signal_name, expected_marker, expected_exit
):
    """Forward drain and cancellation signals to the generic-worker process."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        "#!/bin/sh\n"
        'case " $* " in *" --head "*) echo "location: tag/v1"; exit 0;; esac\n'
        'while [ "$#" -gt 0 ]; do\n'
        '  if [ "$1" = "-o" ]; then output="$2"; shift 2; else shift; fi\n'
        "done\n"
        'case "$output" in\n'
        "  *generic-worker) cat > \"$output\" <<'WORKER'\n"
        "#!/bin/sh\n"
        'if [ "$1" = "new-ed25519-keypair" ]; then\n'
        '  while [ "$#" -gt 0 ]; do\n'
        '    if [ "$1" = "--file" ]; then touch "$2"; break; fi\n'
        "    shift\n"
        "  done\n"
        "  exit 0\n"
        "fi\n"
        "exec python3 fake_worker.py\n"
        "WORKER\n"
        "    ;;\n"
        '  *) printf "#!/bin/sh\\nexit 0\\n" > "$output";;\n'
        "esac\n"
    )
    curl.chmod(0o755)
    (tmp_path / "fake_worker.py").write_text(
        "import signal\n"
        "import time\n"
        "from pathlib import Path\n"
        "Path('ready').touch()\n"
        "def drained(_signum, _frame):\n"
        "    Path('draining').touch()\n"
        "    time.sleep(1)\n"
        "    Path('signal').write_text('int')\n"
        "    raise SystemExit(68)\n"
        "def cancelled(_signum, _frame):\n"
        "    Path('signal').write_text('term')\n"
        "    raise SystemExit(42)\n"
        "signal.signal(signal.SIGINT, drained)\n"
        "signal.signal(signal.SIGTERM, cancelled)\n"
        "while True:\n"
        "    time.sleep(0.05)\n"
    )
    token_file = tmp_path / "github-token"
    token_file.write_text("test-token")
    token_file.chmod(0o600)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "TASKCLUSTER_ACCESS_TOKEN": "tc-test-token",
        "TC_WORKER_ID": "test-worker",
        "ORION_GITHUB_TOKEN_FILE": str(token_file),
        "RUNNER_TEMP": str(tmp_path),
    }
    wrapper = REPO_ROOT / ".github/scripts/start-worker.sh"
    process = subprocess.Popen([str(wrapper)], cwd=tmp_path, env=env)
    try:
        deadline = time.monotonic() + 10
        while not (tmp_path / "ready").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert (tmp_path / "ready").exists()
        process.send_signal(signal.SIGUSR1)
        if signal_name == "TERM":
            deadline = time.monotonic() + 5
            while not (tmp_path / "draining").exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert (tmp_path / "draining").exists()
            process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=15) == expected_exit
        assert (tmp_path / "signal").read_text().strip() == expected_marker
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_service_build_uses_load_compatible_with_docker_save_export():
    """Load the Buildx archive in the format expected by docker save."""
    root = Path(__file__).resolve().parents[3]
    workflow = safe_load((root / ".github/workflows/build-service.yml").read_text())
    build = next(
        step
        for step in workflow["jobs"]["run"]["steps"]
        if step.get("name") == "Build Docker service"
    )

    assert build["with"]["load"] is True
    assert "outputs" not in build["with"]
