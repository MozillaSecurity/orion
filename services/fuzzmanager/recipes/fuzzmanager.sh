#!/bin/bash -ex

#### Install FuzzManager

cd /home/fuzzmanager
git clone --depth 1 --no-tags https://github.com/mozillasecurity/FuzzManager.git
python3 -m pip install ./FuzzManager
# pip install boto
