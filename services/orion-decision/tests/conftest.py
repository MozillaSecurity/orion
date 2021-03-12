# coding: utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Fixtures for Orion Decision tests"""

from unittest import mock

import pytest

from orion_decision.ci_matrix import IMAGES, VERSIONS


@pytest.fixture(scope="session")
def mock_ci_languages():
    """Populate fake language list for use in CIMatrix testing"""
    with (
        mock.patch("orion_decision.ci_matrix.LANGUAGES", ["python", "node"]),
        mock.patch.dict(
            VERSIONS,
            {
                ("python", "linux"): ["3.6", "3.7", "3.8", "3.9"],
                ("python", "windows"): ["3.7"],
                ("node", "linux"): ["12"],
            },
            clear=True,
        ),
        mock.patch.dict(
            IMAGES,
            {
                ("python", "linux", "3.6"): "py36",
                ("python", "linux", "3.7"): "py37",
                ("python", "linux", "3.8"): "py38",
                ("python", "linux", "3.9"): "py39",
                ("python", "windows", "3.7"): "py37-win",
                ("node", "linux", "12"): "node12",
            },
            clear=True,
        ),
    ):
        yield
