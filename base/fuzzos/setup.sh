#!/bin/bash -ex

./recipes/fuzzos.sh
./recipes/llvm.sh
./recipes/rg.sh
./recipes/afl.sh
./recipes/fuzzfetch.sh
./recipes/credstash.sh
./recipes/fuzzmanager.sh
./recipes/honggfuzz.sh
./recipes/breakpad.sh
./recipes/nodejs.sh
./recipes/rr.sh
./recipes/grcov.sh
