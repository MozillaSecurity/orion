#!/bin/bash -ex
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

pushd "$HOME"

# Get more fuzzing prerequisites - have to install as root, else `hg` is not found by the rest of this script
python2 -m pip install --upgrade pip setuptools virtualenv
python3 -m pip install --upgrade pip setuptools

# Get supporting fuzzing libraries via pip, funfuzz will be used as the "funfuzz" user later
pushd "$HOME/funfuzz/"  # For requirements.txt to work properly, we have to be in the repository directory
python2 -m pip install --user --upgrade mercurial
python3 -m pip install --user --upgrade future-breakpoint jsbeautifier
python3 -m pip install --user --upgrade -r requirements.txt
python3 -m pip install --user --upgrade ".[test]"
popd

popd
