#!/usr/bin/env bash

set -e
set -x

#### Install FuzzManager

cd "$HOME"
git clone --depth 1 --no-tags https://github.com/mozillasecurity/fuzzmanager.git
pip install ./fuzzmanager
pip install boto
