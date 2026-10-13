from __future__ import annotations

from pathlib import Path

import pytest

from ci import build


def test_build_loads_dirty_parent_archive_for_a_different_supported_arch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent_archive = tmp_path / "artifacts" / "image-base-amd64" / "base-amd64.tar.zst"
    parent_archive.parent.mkdir(parents=True)
    parent_archive.touch()
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(build, "run", lambda *args: calls.append(args))
    plan = {
        "dirty": ["base", "code-only"],
        "services": {
            "base": {
                "kind": "docker",
                "archs": ["amd64"],
                "dependencies": [],
                "dockerfile": "base/Dockerfile",
                "context": ".",
            },
            "code-only": {"kind": "docker", "archs": ["amd64"]},
            "app": {
                "kind": "docker",
                "archs": ["amd64", "arm64"],
                "dependencies": ["base", "code-only"],
                "image_dependencies": ["base"],
                "dockerfile": "app/Dockerfile",
                "context": ".",
            },
        },
    }

    result = build.build(
        plan, "app", "arm64", tmp_path / "artifacts", tmp_path / "output"
    )

    assert result == tmp_path / "output" / "app-arm64.tar.zst"
    assert ("podman", "load", "--input", str(parent_archive)) in calls
    assert (
        "podman",
        "tag",
        "docker.io/mozillasecurity/base:latest-amd64",
        "docker.io/mozillasecurity/base:latest",
    ) in calls
    assert any("linux/arm64" in call for call in calls)
    assert not any(call[:2] == ("podman", "pull") for call in calls)


def test_build_fails_if_a_dirty_parent_artifact_is_missing(tmp_path: Path) -> None:
    plan = {
        "dirty": ["base"],
        "services": {
            "base": {
                "kind": "docker",
                "archs": ["amd64"],
                "dependencies": [],
                "dockerfile": "base/Dockerfile",
                "context": ".",
            },
            "app": {
                "kind": "docker",
                "archs": ["amd64"],
                "dependencies": ["base"],
                "dockerfile": "app/Dockerfile",
                "context": ".",
            },
        },
    }

    with pytest.raises(FileNotFoundError, match="Missing rebuilt dependency"):
        build.build(plan, "app", "amd64", tmp_path / "artifacts", tmp_path / "output")


def test_clean_parent_pull_is_tagged_as_default_from_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(build, "run", lambda *args: calls.append(args))
    plan = {
        "dirty": [],
        "services": {
            "base": {
                "kind": "docker",
                "archs": ["amd64"],
                "dependencies": [],
                "dockerfile": "base/Dockerfile",
                "context": ".",
            },
            "app": {
                "kind": "docker",
                "archs": ["amd64"],
                "dependencies": ["base"],
                "dockerfile": "app/Dockerfile",
                "context": ".",
            },
        },
    }

    build.build(plan, "app", "amd64", tmp_path / "artifacts", tmp_path / "output")

    assert ("podman", "pull", "docker.io/mozillasecurity/base:latest-amd64") in calls
    assert (
        "podman",
        "tag",
        "docker.io/mozillasecurity/base:latest-amd64",
        "docker.io/mozillasecurity/base:latest",
    ) in calls
