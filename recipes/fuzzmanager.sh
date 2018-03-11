#!/bin/bash -ex

cd /home/worker
git clone --depth 1 https://github.com/mozillasecurity/fuzzmanager.git
pip install ./fuzzmanager
