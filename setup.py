#!/usr/bin/env python
# coding=utf-8
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""top-level setup.py required by pre-commit to install services/orion-decision"""
from os import chdir, execv
from pathlib import Path
import sys


if __name__ == "__main__":
    assert Path(sys.argv[0]).name == "setup.py", f"unknown args: {sys.argv}"
    chdir(Path(__file__).parent / "services" / "orion-decision")
    argv = [sys.executable, "setup.py"] + sys.argv[1:]
    execv(sys.executable, argv)
