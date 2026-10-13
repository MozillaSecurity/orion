from __future__ import annotations

from ci import download_dependencies


def test_downloads_only_dirty_docker_parents_at_selected_arch(
    tmp_path, monkeypatch
) -> None:
    calls: list[tuple[list[str], dict]] = []

    def fake_run(command, *, check, env):
        calls.append((command, {"check": check, "env": env}))

    monkeypatch.setattr(download_dependencies.subprocess, "run", fake_run)
    plan = {
        "dirty": ["base", "code-only"],
        "services": {
            "base": {"kind": "docker", "archs": ["amd64"]},
            "code-only": {"kind": "docker", "archs": ["amd64"]},
            "msys-parent": {"kind": "msys", "archs": ["amd64"]},
            "app": {
                "kind": "docker",
                "archs": ["amd64", "arm64"],
                "dependencies": ["base", "code-only", "msys-parent"],
                "image_dependencies": ["base"],
            },
        },
    }

    result = download_dependencies.download_dependencies(
        plan, "app", "arm64", "100", "org/repo", "token", tmp_path
    )

    assert result == ["image-base-amd64"]
    assert [call[0] for call in calls] == [
        [
            "gh",
            "run",
            "download",
            "100",
            "--repo",
            "org/repo",
            "--name",
            "image-base-amd64",
            "--dir",
            str(tmp_path / "image-base-amd64"),
        ]
    ]
    assert all(call[1]["check"] for call in calls)
    assert all(call[1]["env"]["GH_TOKEN"] == "token" for call in calls)
