# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Tests for Orion CI matrix loading"""

from pathlib import Path
from typing import List

import pytest
from yaml import safe_load as yaml_load

from orion_decision.ci_matrix import (
    CIArtifact,
    CIMatrix,
    CISecret,
    CISecretEnv,
    CISecretFile,
    CISecretKey,
    MatrixJob,
)

FIXTURES = (Path(__file__).parent / "fixtures").resolve()
pytestmark = pytest.mark.usefixtures("mock_ci_languages")


@pytest.mark.parametrize(
    "fixture",
    [
        # basic load test
        "matrix01",
        # env loading
        "matrix02",
        # job.includes
        "matrix03",
        # job.excludes
        "matrix05",
        # secrets
        "matrix07",
        # artifacts
        "matrix08",
    ],
)
def test_matrix_load(fixture: str) -> None:
    """simple matrix load"""
    obj = yaml_load((FIXTURES / fixture / "matrix.yaml").read_text())
    exp = yaml_load((FIXTURES / fixture / "expected.yaml").read_text())
    assert set(exp) == {"jobs", "secrets", "artifacts"}
    mtx = CIMatrix(obj, "master", False)
    jobs = {str(MatrixJob.from_json(data)) for data in exp["jobs"]}
    assert {str(job) for job in mtx.jobs} == jobs
    secrets = {str(CISecret.from_json(data)) for data in exp["secrets"]}
    assert {str(sec) for sec in mtx.secrets} == secrets
    artifacts = {str(CIArtifact.from_json(data)) for data in exp["artifacts"]}
    assert {str(art) for art in mtx.artifacts} == artifacts


@pytest.mark.parametrize(
    "case, branch, event_type",
    [
        ("release", "dev", "release"),
        ("on_branch", "main", "push"),
        ("off_branch", "dev", "push"),
    ],
)
def test_matrix_release(case: str, branch: str, event_type: str) -> None:
    """test job `when` conditions"""
    obj = yaml_load((FIXTURES / "matrix04" / "matrix.yaml").read_text())
    exp = yaml_load((FIXTURES / "matrix04" / f"expected_{case}.yaml").read_text())
    assert set(exp) == {"jobs", "secrets", "artifacts"}
    mtx = CIMatrix(obj, branch, event_type)
    jobs = {str(MatrixJob.from_json(data)) for data in exp["jobs"]}
    assert {str(job) for job in mtx.jobs} == jobs
    assert not exp["secrets"]
    assert not mtx.secrets


def test_matrix_unused(caplog: pytest.LogCaptureFixture) -> None:
    """test that unused CI matrix dimensions trigger a warning"""
    obj = yaml_load((FIXTURES / "matrix06" / "matrix.yaml").read_text())
    mtx = CIMatrix(obj, "master", False)
    assert not mtx.secrets
    assert not mtx.jobs
    assert any(rec.levelname == "WARNING" for rec in caplog.get_records("call"))

    caplog.clear()
    del obj["language"]
    mtx = CIMatrix(obj, "master", False)
    assert not mtx.secrets
    assert not mtx.jobs
    assert any(rec.levelname == "WARNING" for rec in caplog.get_records("call"))


@pytest.mark.parametrize(
    "secrets",
    [
        [],
        [CISecretEnv("project/secret", "B")],
        [CISecretKey("project/deploy")],
    ],
)
@pytest.mark.parametrize(
    "artifacts",
    [
        [],
        [CIArtifact("file", "/src", "public/log.txt")],
    ],
)
def test_matrix_job_serialize(
    secrets: List[CISecret], artifacts: List[CIArtifact]
) -> None:
    """test that MatrixJob serialize/deserialize is lossless"""
    job = MatrixJob(
        "name",
        "python",
        "3.9",
        "linux",
        {"A": "abc"},
        ["test"],
        stage=2,
        previous_pass=True,
    )
    job.secrets.extend(secrets)
    job.artifacts.extend(artifacts)
    job_json = str(job)
    if secrets:
        assert all(secret.secret in job_json for secret in secrets if secret)
    if artifacts:
        assert all(artifact.url in job_json for artifact in artifacts)
    job2 = MatrixJob.from_json(job_json)
    assert job == job2


@pytest.mark.parametrize(
    "secret",
    [
        CISecretEnv("project/secret", "A"),
        CISecretEnv("project/secret", "A", key="obj"),
        CISecretFile("project/secret", "/path/to/cfg"),
        CISecretFile("project/secret", "/path/to/cfg", key="obj"),
        CISecretKey("project/secret"),
        CISecretKey("project/secret", key="obj"),
        CISecretKey("project/secret", hostname="repo"),
        CISecretKey("project/secret", hostname="repo", key="obj"),
    ],
)
def test_matrix_secret_serialize(secret: CISecret) -> None:
    """test that CISecret serialize/deserialize is lossless"""
    secret2 = CISecret.from_json(str(secret))
    assert secret == secret2
