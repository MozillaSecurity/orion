#!/bin/bash -ex

./recipes/llvm.sh
./recipes/afl.sh
./recipes/fuzzfetch.sh
./recipes/fuzzmanager.sh

apt-get clean -y \
&& apt-get autoclean -y \
&& apt-get autoremove -y \
&& rm -rf /var/lib/apt/lists/ \
&& rm -rf /root/.cache/*
