#!/bin/bash -ex

#### FuzzFetch

cd $HOME
git clone --depth 1 https://github.com/mozillasecurity/fuzzfetch
pip install -r fuzzfetch/requirements.txt
