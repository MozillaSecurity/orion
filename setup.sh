#!/bin/bash -ex

bash recipes/llvm.sh
bash recipes/fuzzmanager.sh
bash recipes/afl.sh
bash recipes/fuzzfetch.sh

apt-get clean -y \
&& apt-get autoclean -y \
&& apt-get autoremove -y \
&& rm -rf /var/lib/apt/lists/ \
&& rm -rf /root/.cache/*
