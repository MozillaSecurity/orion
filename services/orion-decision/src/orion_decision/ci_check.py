# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Checker for CI build matrix"""


import argparse
from logging import getLogger
from pathlib import Path

from jsone import render as jsone_render
from taskcluster.utils import slugId
from yaml import dump as yaml_dump
from yaml import safe_load as yaml_load

from .ci_matrix import CIMatrix
from .git import GIT_EVENT_TYPES

LOG = getLogger(__name__)
EVENTS_PATH = Path(__file__).parent / "github_test_events"


def check_matrix(args: argparse.Namespace) -> None:
    """Check whether the CI matrix found in .taskcluster.yml can be loaded.

    Raises if any error is found.

    Arguments:
        args: Arguments as returned by `parse_ci_check_args()`
    """
    for changed in args.changed:
        # is it a taskcluster.yml?
        if changed.name != ".taskcluster.yml":
            LOG.warning("Skipping unknown file: %s", changed)
            continue

        # use test data to render it
        for event in EVENTS_PATH.glob("*.yaml"):
            event_data = yaml_load(event.read_text())
            rendered_taskcluster_yml = jsone_render(
                yaml_load(changed.read_text()),
                context={
                    "taskcluster_root_url": "https://tc.mozilla.com",
                    "tasks_for": event_data["action"],
                    "as_slugid": slugId,
                    "event": event_data["event"],
                },
            )

            # for each resulting task
            for task in rendered_taskcluster_yml.get("tasks", []):
                # skip malformed tasks ...
                # taskcluster_yml_validator will catch it
                if (
                    "payload" not in task
                    or "image" not in task["payload"]
                    or "command" not in task["payload"]
                ):
                    continue

                # does it use orion-decision image and call ci-decision?
                cmd = yaml_dump(task["payload"]["command"])
                if (
                    "orion-decision" not in yaml_dump(task["payload"]["image"])
                    or "ci-decision" not in cmd
                ):
                    continue

                # does that job have a CI_MATRIX env var or pass --matrix? (fail if not)
                if "--matrix" in cmd:
                    raise NotImplementedError(
                        "checking --matrix isn't supported yet, use CI_MATRIX"
                    )
                assert "CI_MATRIX" in task["payload"].get(
                    "env", {}
                ), "CI_MATRIX is missing (required by ci-decision)"
                matrix = yaml_load(task["payload"]["env"]["CI_MATRIX"])

                # get all `branch:` references
                branches = {None}
                if "jobs" in matrix and "include" in matrix["jobs"]:
                    for include in matrix["jobs"]["include"]:
                        if "on" in include and "branch" in include["on"]:
                            branches.add(include["on"]["branch"])

                # create CIMatrix for each branch and is_release=True
                event_type = GIT_EVENT_TYPES[event_data["action"]]
                for branch in branches:
                    CIMatrix(matrix, branch, event_type)
                CIMatrix(matrix, None, event_type)
