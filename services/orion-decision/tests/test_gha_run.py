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

from orion_decision import gha_publish, gha_run
from orion_decision.gha_plan import job_id

REPO_ROOT = Path(__file__).resolve().parents[3]
_resolve_artifact_name = gha_run._artifact_name


@pytest.fixture(autouse=True)
def default_artifact_name(monkeypatch):
    """Keep unrelated operation tests independent of the Actions API boundary."""
    monkeypatch.setattr(
        gha_run,
        "_artifact_name",
        lambda name, arch: (
            f"orion-build-{name}-{arch}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
        ),
    )


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def make_repo(root: Path, files: dict[str, str]) -> tuple[Path, str]:
    root.mkdir()
    git(root, "init", "-b", "main")
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


def test_selected_dependency_uses_latest_earlier_attempt_archive(
    tmp_path, monkeypatch
) -> None:
    """Reuse the latest live earlier attempt artifact for a selected dependency."""
    repo, revision = docker_repo(tmp_path / "repo")
    patch_archive_io(monkeypatch)
    current_run: list[tuple[str, Path]] = []
    indexed: list[tuple[str, str, Path]] = []

    def download_artifact(name: str, destination: Path) -> None:
        current_run.append((name, destination))
        destination.mkdir(parents=True)
        (destination / "base-amd64.tar.zst").touch()

    monkeypatch.setattr(gha_run, "_download_artifact", download_artifact)
    for key, value in {
        "GITHUB_RUN_ID": "77",
        "GITHUB_REPOSITORY": "MozillaSecurity/orion",
        "GITHUB_TOKEN": "token",
        "GITHUB_RUN_ATTEMPT": "3",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        gha_publish,
        "_actions_artifacts",
        lambda *_args: [
            {"name": "orion-build-base-amd64-1", "id": 1},
            {"name": "orion-build-base-amd64-2", "id": 2, "expired": True},
            {"name": "orion-build-base-amd64-4", "id": 4},
            {"name": "orion-build-base-arm64-1", "id": 5},
        ],
    )
    monkeypatch.setattr(gha_run, "_artifact_name", _resolve_artifact_name)
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


def test_native_tox_test_runs_from_service_directory_with_ci_environment(
    tmp_path, monkeypatch
):
    """Run a host Python check from the service directory with CI enabled."""
    repo, revision = make_repo(
        tmp_path / "repo",
        {
            "services/alpha/service.yaml": (
                "name: alpha\ntests:\n  - name: py310\n    type: tox\n"
                "    python: '3.10'\n    toxenv: py310\n"
            ),
            "services/alpha/tox.ini": "[tox]\n",
            "services/alpha/Dockerfile": "FROM alpine:3.20\n",
        },
    )
    monkeypatch.setattr(gha_run.sys, "version_info", SimpleNamespace(major=3, minor=10))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    calls: list[tuple[list[str], dict[str, Any]]] = []
    monkeypatch.setattr(
        gha_run, "_run", lambda command, **kwargs: calls.append((command, kwargs))
    )

    gha_run.run_tests(
        repo,
        "alpha",
        revision,
        plan(revision, job_id("service_test", "alpha")),
        test_index=0,
    )

    assert calls == [
        (
            ["tox", "-e", "py310"],
            {
                "cwd": repo / "services/alpha",
                "env": {**os.environ, "CI": "true"},
            },
        )
    ]


def test_native_tox_test_rejects_unavailable_python_version(tmp_path, monkeypatch):
    """Stop when the active interpreter cannot satisfy the selected check."""
    repo, revision = make_repo(
        tmp_path / "repo",
        {
            "services/alpha/service.yaml": (
                "name: alpha\ntests:\n  - name: py310\n    type: tox\n"
                "    python: '3.10'\n    toxenv: py310\n"
            ),
            "services/alpha/Dockerfile": "FROM alpine:3.20\n",
        },
    )
    monkeypatch.setattr(gha_run.sys, "version_info", SimpleNamespace(major=3, minor=11))
    monkeypatch.setattr(
        gha_run, "_run", lambda *_args, **_kwargs: pytest.fail("wrong Python ran tox")
    )

    with pytest.raises(
        RuntimeError,
        match=r"requires Python 3\.10.*current runtime is Python 3\.11",
    ):
        gha_run.run_tests(
            repo,
            "alpha",
            revision,
            plan(revision, job_id("service_test", "alpha")),
            test_index=0,
        )


def test_service_test_index_must_select_an_existing_tox_test(tmp_path, monkeypatch):
    """Reject test selectors that cannot identify a configured tox check."""
    repo, revision = make_repo(
        tmp_path / "repo",
        {
            "services/alpha/service.yaml": (
                "name: alpha\ntests:\n  - name: py310\n    type: tox\n"
                "    python: '3.10'\n    toxenv: py310\n"
            ),
            "services/alpha/Dockerfile": "FROM alpine:3.20\n",
        },
    )
    selected_plan = plan(revision, job_id("service_test", "alpha"))

    for index in (-1, 1):
        with pytest.raises(ValueError, match="Test index"):
            gha_run.run_tests(repo, "alpha", revision, selected_plan, test_index=index)


def test_native_checks_for_multiple_python_versions_need_a_selector(
    tmp_path, monkeypatch
):
    """Require an explicit matrix row when service checks use different interpreters."""
    repo, revision = make_repo(
        tmp_path / "repo",
        {
            "services/alpha/service.yaml": (
                "name: alpha\ntests:\n  - name: py310\n    type: tox\n"
                "    python: '3.10'\n    toxenv: py310\n"
                "  - name: py311\n    type: tox\n"
                "    python: '3.11'\n    toxenv: py311\n"
            ),
            "services/alpha/Dockerfile": "FROM alpine:3.20\n",
        },
    )
    monkeypatch.setattr(
        gha_run, "_run", lambda *_args, **_kwargs: pytest.fail("unselected check ran")
    )

    with pytest.raises(ValueError, match=r"multiple Python versions.*--test-index"):
        gha_run.run_tests(
            repo, "alpha", revision, plan(revision, job_id("service_test", "alpha"))
        )


def test_native_test_index_runs_only_the_selected_entry(tmp_path, monkeypatch):
    """Run only the matrix row identified by its position in service metadata."""
    repo, revision = make_repo(
        tmp_path / "repo",
        {
            "services/alpha/service.yaml": (
                "name: alpha\ntests:\n  - name: lint\n    type: tox\n"
                "    python: '3.10'\n    toxenv: lint\n"
                "  - name: unit\n    type: tox\n"
                "    python: '3.10'\n    toxenv: unit\n"
            ),
            "services/alpha/Dockerfile": "FROM alpine:3.20\n",
        },
    )
    monkeypatch.setattr(gha_run.sys, "version_info", SimpleNamespace(major=3, minor=10))
    monkeypatch.delenv("CI", raising=False)
    commands: list[tuple[list[str], dict[str, Any]]] = []
    monkeypatch.setattr(
        gha_run, "_run", lambda command, **kwargs: commands.append((command, kwargs))
    )

    gha_run.run_tests(
        repo,
        "alpha",
        revision,
        plan(revision, job_id("service_test", "alpha")),
        test_index=1,
    )

    assert commands == [
        (
            ["tox", "-e", "unit"],
            {"cwd": repo / "services/alpha", "env": {**os.environ, "CI": "true"}},
        )
    ]


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


def test_docker_staging_uses_attempt_tags_and_returns_exact_oci_digests(
    tmp_path, monkeypatch
):
    """Stage the newest available archive for each arch of this service."""
    repo, revision = make_repo(
        tmp_path / "repo",
        {
            "services/multi/service.yaml": "name: multi\narch: [amd64, arm64]\n",
            "services/multi/Dockerfile": "FROM alpine:3.20\n",
            "services/peer/service.yaml": "name: peer\n",
            "services/peer/Dockerfile": "FROM alpine:3.20\n",
        },
    )
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.setenv("GITHUB_REPOSITORY", "MozillaSecurity/orion")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    builds = {
        job_id("build", "multi", "amd64"): {"result": "success"},
        job_id("build", "multi", "arm64"): {"result": "success"},
        job_id("build", "peer", "amd64"): {"result": "failure"},
    }
    monkeypatch.setenv("ORION_JOB_RESULTS", json.dumps(builds))
    monkeypatch.setattr(
        gha_publish,
        "_actions_artifacts",
        lambda *_args: [
            {"id": 1, "name": "orion-build-multi-amd64-1"},
            {"id": 2, "name": "orion-build-multi-amd64-2", "expired": True},
            {"id": 3, "name": "orion-build-multi-arm64-2"},
            {"id": 4, "name": "orion-build-multi-arm64-3"},
        ],
    )
    monkeypatch.setattr(gha_run, "_artifact_name", _resolve_artifact_name)
    uploaded: list[str] = []
    downloaded: list[str] = []
    digests = iter(("a" * 64, "b" * 64))

    def download_artifact(name: str, destination: Path) -> None:
        downloaded.append(name)
        destination.mkdir(parents=True)
        (destination / f"multi-{name.rsplit('-', 2)[-2]}.tar.zst").touch()

    def run(command: list[str], **_kwargs: Any) -> None:
        if command[0] == "zstd":
            Path(command[command.index("-o") + 1]).touch()
        else:
            assert command[:4] == ["skopeo", "copy", "--format", "oci"]
            assert Path(command[-2].removeprefix("docker-archive:")).is_file()
            Path(command[command.index("--digestfile") + 1]).write_text(
                f"sha256:{next(digests)}\n"
            )
            uploaded.append(command[-1])

    monkeypatch.setattr(gha_run, "_download_artifact", download_artifact)
    monkeypatch.setattr(gha_run, "_run", run)
    plan = {"revision": revision, "publish": True, "selected_jobs": list(builds)}

    assert gha_run.stage_images(repo, plan, "multi", tmp_path / "runner") == {
        "amd64": "sha256:" + "a" * 64,
        "arm64": "sha256:" + "b" * 64,
    }
    assert downloaded == ["orion-build-multi-amd64-1", "orion-build-multi-arm64-2"]
    assert uploaded == [
        f"docker://mozillasecurity/multi:gha-{revision}-12345-2-amd64",
        f"docker://mozillasecurity/multi:gha-{revision}-12345-2-arm64",
    ]


@pytest.mark.parametrize(
    (
        "current_position",
        "current_run",
        "current_attempt",
        "latest_position",
        "latest_run",
        "latest_attempt",
        "legacy",
        "promoted",
    ),
    [
        (2, 200, 3, None, None, None, False, True),
        (2, 200, 3, 2, 199, 9, False, True),
        (2, 200, 3, 2, 201, 1, False, False),
        (2, 200, 3, 2, 200, 2, False, True),
        (2, 200, 3, 2, 200, 4, False, False),
        (1, 200, 3, 3, 199, 1, False, False),
        (2, 200, 3, 1, 201, 9, False, True),
        (1, 200, 3, 2, 199, 1, True, False),
        (2, 200, 3, 1, 201, 9, True, True),
    ],
)
def test_docker_promotion_orders_service_latest(
    tmp_path,
    monkeypatch,
    current_position,
    current_run,
    current_attempt,
    latest_position,
    latest_run,
    latest_attempt,
    legacy,
    promoted,
):
    """Use the service's actual index and main landing order before run identity."""
    repo, first = make_repo(
        tmp_path / "repo",
        {
            "services/multi/service.yaml": "name: multi\narch: [amd64, arm64]\n",
            "services/multi/Dockerfile": "FROM alpine:3.20\n",
        },
    )
    git(repo, "commit", "--allow-empty", "-m", "land second")
    second = git(repo, "rev-parse", "HEAD")
    git(repo, "commit", "--allow-empty", "-m", "land third")
    third = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/main", third)
    revisions = [None, first, second, third]
    revision = revisions[current_position]
    git(repo, "checkout", "--detach", revision)

    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_RUN_NUMBER", str(current_run))
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", str(current_attempt))
    annotations = {}
    if latest_position:
        annotations = {
            "org.mozilla.orion.github-run-id": "99999",
            "org.mozilla.orion.github-run-attempt": str(latest_attempt),
        }
        if legacy:
            monkeypatch.setattr(
                gha_run,
                "_legacy_docker_run",
                lambda _run_id: {
                    "head_sha": revisions[latest_position],
                    "run_number": latest_run,
                },
            )
        else:
            annotations.update(
                {
                    "org.mozilla.orion.revision": revisions[latest_position],
                    "org.mozilla.orion.github-run-number": str(latest_run),
                }
            )
    monkeypatch.setattr(gha_run, "_latest_image_annotations", lambda _name: annotations)
    commands: list[list[str]] = []
    monkeypatch.setattr(gha_run, "_run", commands.append)
    digests = {"amd64": "sha256:" + "a" * 64, "arm64": "sha256:" + "b" * 64}

    output = gha_run.promote_images(
        repo,
        {"revision": revision, "publish": True, "landing_order": current_position},
        "multi",
        digests,
        tmp_path,
    )

    receipt = json.loads(output.read_text())["multi"]
    assert receipt["latest_published"] is promoted
    assert receipt["architectures"] == digests
    if promoted:
        assert len(commands) == 1
        command = commands[0]
        assert command[:6] == [
            "docker",
            "buildx",
            "imagetools",
            "create",
            "--tag",
            "mozillasecurity/multi:latest",
        ]
        assert f"index:org.mozilla.orion.revision={revision}" in command
        assert "index:org.mozilla.orion.github-run-id=12345" in command
        assert f"index:org.mozilla.orion.github-run-number={current_run}" in command
        assert (
            f"index:org.mozilla.orion.github-run-attempt={current_attempt}" in command
        )
        assert command[-2:] == [
            f"mozillasecurity/multi@{digest}" for digest in digests.values()
        ]
    else:
        assert commands == []
        assert receipt["superseded"] is True


@pytest.mark.parametrize(
    ("error", "missing"),
    [
        ("manifest unknown", True),
        ("ERROR: docker.io/mozillasecurity/target:latest: not found", True),
        ("ERROR: docker.io/mozillasecurity/peer:latest: not found", False),
        ("unauthorized", False),
    ],
)
def test_docker_latest_inspect_distinguishes_missing_tag_from_other_failures(
    monkeypatch, error, missing
):
    """Only a confirmed missing manifest permits a first promotion."""
    monkeypatch.setattr(
        gha_run.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stderr=error),
    )
    if missing:
        assert gha_run._latest_image_annotations("target") == {}
    else:
        with pytest.raises(RuntimeError, match="Could not inspect latest manifest"):
            gha_run._latest_image_annotations("target")


@pytest.mark.parametrize(
    ("signal_name", "worker_exit", "expected_marker", "expected_exit"),
    [
        ("USR1", 71, "int", 0),
        ("USR1", 68, "int", 0),
        ("TERM", 71, "term", 143),
        (None, 71, None, 71),
    ],
)
def test_worker_wrapper_forwards_drain_and_cancel_signals(
    tmp_path, signal_name, worker_exit, expected_marker, expected_exit
):
    """Accept drained worker exits, preserve cancellation, and reject stray 71."""
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
        "def drained(_signum, _frame):\n"
        "    Path('draining').touch()\n"
        "    time.sleep(1)\n"
        "    Path('signal').write_text('int')\n"
        f"    raise SystemExit({worker_exit})\n"
        "def cancelled(_signum, _frame):\n"
        "    Path('signal').write_text('term')\n"
        "    raise SystemExit(42)\n"
        "signal.signal(signal.SIGINT, drained)\n"
        "signal.signal(signal.SIGTERM, cancelled)\n"
        "Path('ready').touch()\n"
        f"exit_without_signal = {worker_exit if signal_name is None else 0}\n"
        "if exit_without_signal:\n"
        "    raise SystemExit(exit_without_signal)\n"
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
        if signal_name is None:
            assert process.wait(timeout=15) == expected_exit
        else:
            process.send_signal(signal.SIGUSR1)
        if signal_name == "TERM":
            deadline = time.monotonic() + 5
            while not (tmp_path / "draining").exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert (tmp_path / "draining").exists()
            process.send_signal(signal.SIGTERM)
        if signal_name is not None:
            assert process.wait(timeout=15) == expected_exit
        if expected_marker is not None:
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
