from __future__ import annotations

import io
import json
from urllib.request import Request

from ci import baseline


def test_previous_success_skips_current_failed_and_unrelated_runs(monkeypatch) -> None:
    response = {
        "workflow_runs": [
            {"id": 10, "event": "push", "head_sha": "current", "conclusion": "success"},
            {
                "id": 9,
                "event": "workflow_dispatch",
                "head_sha": "failed",
                "conclusion": "failure",
            },
            {
                "id": 8,
                "event": "pull_request",
                "head_sha": "pr",
                "conclusion": "success",
            },
            {
                "id": 7,
                "event": "push",
                "head_sha": "unrelated",
                "conclusion": "success",
            },
            {
                "id": 6,
                "event": "schedule",
                "head_sha": "older",
                "conclusion": "success",
            },
        ]
    }
    monkeypatch.setattr(
        baseline,
        "urlopen",
        lambda request, timeout: io.BytesIO(json.dumps(response).encode()),
    )
    checked: list[str] = []

    def is_ancestor(command, check=False, **kwargs):
        checked.append(command[3])
        return type("Result", (), {"returncode": int(command[3] == "unrelated")})()

    monkeypatch.setattr(baseline.subprocess, "run", is_ancestor)

    assert baseline.previous_success("org/repo", "token", "10") == "older"
    assert checked == ["unrelated", "older"]


def test_previous_success_includes_workflow_dispatch_baseline(monkeypatch) -> None:
    response = {
        "workflow_runs": [
            {
                "id": 12,
                "event": "workflow_dispatch",
                "head_sha": "manual",
                "conclusion": "success",
            }
        ]
    }
    request_seen: list[Request] = []

    def open_request(request, timeout):
        request_seen.append(request)
        return io.BytesIO(json.dumps(response).encode())

    monkeypatch.setattr(baseline, "urlopen", open_request)
    monkeypatch.setattr(
        baseline.subprocess,
        "run",
        lambda *args, **kwargs: type("Result", (), {"returncode": 0})(),
    )

    assert baseline.previous_success("org/repo", "token", "13") == "manual"
    assert "status=success" in request_seen[0].full_url
    assert "branch=main" in request_seen[0].full_url
