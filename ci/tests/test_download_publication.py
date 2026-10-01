from __future__ import annotations

from ci import download_publication


def test_docker_download_names_are_exact_arches(tmp_path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        download_publication.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )
    plan = {"services": {"grizzly": {"kind": "docker", "archs": ["amd64", "arm64"]}}}

    names = download_publication.download_publication(
        plan, "grizzly", "42", "org/repo", "token", tmp_path
    )

    assert names == ["image-grizzly-amd64", "image-grizzly-arm64"]
    assert [command[0] for command in calls] == [
        [
            "gh",
            "run",
            "download",
            "42",
            "--repo",
            "org/repo",
            "--name",
            name,
            "--dir",
            str(tmp_path / "grizzly"),
        ]
        for name in ("image-grizzly-amd64", "image-grizzly-arm64")
    ]


def test_msys_download_uses_exact_artifact_name(tmp_path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        download_publication.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command),
    )

    names = download_publication.download_publication(
        {"services": {"bugmon-win": {"kind": "msys"}}},
        "bugmon-win",
        "42",
        "org/repo",
        "token",
        tmp_path,
    )

    assert names == ["image-bugmon-win-msys"]
    assert calls == [
        [
            "gh",
            "run",
            "download",
            "42",
            "--repo",
            "org/repo",
            "--name",
            "image-bugmon-win-msys",
            "--dir",
            str(tmp_path / "bugmon-win"),
        ]
    ]
