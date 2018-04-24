#!/bin/bash -ex

cd /home/worker
git clone --depth 1 --no-tags https://github.com/mozillasecurity/fuzzmanager.git
pip install ./fuzzmanager
