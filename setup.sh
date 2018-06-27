#!/bin/bash -ex

./recipes/fuzzos.sh
./recipes/llvm.sh
./recipes/afl.sh
./recipes/fuzzfetch.sh
./recipes/credstash.sh
./recipes/fuzzmanager.sh
./recipes/honggfuzz.sh
./recipes/mdsw.sh
./recipes/nodejs.sh
./recipes/rr.sh
./recipes/grcov.sh
