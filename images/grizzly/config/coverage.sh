#!/bin/sh -ex

"$@"

grcov ~/firefox -s ~/mozilla-central -t coveralls --token 1111111 -p '/home/worker/workspace/build/src' --commit-sha "$revision" > ~/coveralls.json
python -m CovReporter.CovReporter --submit ~/coveralls.json --repository mozilla-central
python -m EC2Reporter.EC2Reporter --disable $EC2SPOTMANAGER_POOLID
