# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Focused tests for GitHub Actions operation execution."""

import io
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from yaml import safe_load

from orion_decision import gha_run
from orion_decision.gha_plan import job_id


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
            "orion-build-base-amd64",
            tmp_path / "runner/dependencies/orion-build-base-amd64",
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

    assert artifact_names == ["orion-build-base.service-amd64"]


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
        assert sum(command[:2] == ["cmd.exe", "/c"] for command, _ in commands) == 2
        assert any(
            "bash.exe" in command[0] and any(arg.startswith("-l") for arg in command)
            for command, _ in commands
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
        (destination / f"multi-{name.rsplit('-', 1)[-1]}.tar.zst").touch()

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


def test_stale_publication_is_rejected_against_current_branch_head(monkeypatch):
    """Reject publication when the workflow revision is no longer the branch head."""
    monkeypatch.setattr(
        gha_run.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="newer-revision\n"),
    )

    with pytest.raises(RuntimeError, match="Refusing stale publication"):
        gha_run.reject_stale_publication("org/orion", "master", "older-revision")


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
