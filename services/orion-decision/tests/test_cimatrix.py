# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Tests for Orion CI matrix loading"""

from pathlib import Path

import pytest
from yaml import safe_load as yaml_load

from orion_decision.ci_matrix import (
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
    ],
)
def test_matrix_load(fixture):
    """simple matrix load"""
    obj = yaml_load((FIXTURES / fixture / "matrix.yaml").read_text())
    exp = yaml_load((FIXTURES / fixture / "expected.yaml").read_text())
    assert set(exp) == {"jobs", "secrets"}
    mtx = CIMatrix(obj, "master", False)
    jobs = set(str(MatrixJob.from_json(data)) for data in exp["jobs"])
    assert set(str(job) for job in mtx.jobs) == jobs
    secrets = set(str(CISecret.from_json(data)) for data in exp["secrets"])
    assert set(str(sec) for sec in mtx.secrets) == secrets


@pytest.mark.parametrize(
    "case, branch, release",
    [
        ("release", "dev", "release"),
        ("on_branch", "main", "push"),
        ("off_branch", "dev", "push"),
    ],
)
def test_matrix_release(case, branch, release):
    """test job `when` conditions"""
    obj = yaml_load((FIXTURES / "matrix04" / "matrix.yaml").read_text())
    exp = yaml_load((FIXTURES / "matrix04" / f"expected_{case}.yaml").read_text())
    assert set(exp) == {"jobs", "secrets"}
    mtx = CIMatrix(obj, branch, release)
    jobs = set(str(MatrixJob.from_json(data)) for data in exp["jobs"])
    assert set(str(job) for job in mtx.jobs) == jobs
    assert not exp["secrets"]
    assert not mtx.secrets


def test_matrix_unused(caplog):
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
def test_matrix_job_serialize(secrets):
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
    job_json = str(job)
    if secrets:
        assert all(secret.secret in job_json for secret in secrets)
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
def test_matrix_secret_serialize(secret):
    """test that CISecret serialize/deserialize is lossless"""
    secret2 = CISecret.from_json(str(secret))
    assert secret == secret2
