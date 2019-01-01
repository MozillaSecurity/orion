#!/bin/bash -ex

pushd "$HOME"

# Get more fuzzing prerequisites - have to install as root, else `hg` is not found by the rest of this script
python2 -m pip install --upgrade pip setuptools virtualenv
python3 -m pip install --upgrade pip setuptools

# Get supporting fuzzing libraries via pip, funfuzz will be used as the "funfuzz" user later
pushd "$HOME/funfuzz/"  # For requirements.txt to work properly, we have to be in the repository directory
python2 -m pip install --user --upgrade mercurial
python3 -m pip install --user --upgrade future-breakpoint
python3 -m pip install --user --upgrade -r requirements.txt
python3 -m pip install --user --upgrade ".[test]"
popd

popd
