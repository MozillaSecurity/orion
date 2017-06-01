#!/bin/bash -ex

bash receipes/llvm.sh
bash receipes/fuzzmanager.sh
bash receipes/afl.sh
bash receipes/fuzzfetch.sh

apt-get clean -y \
&& apt-get autoclean -y \
&& apt-get autoremove -y \
&& rm -rf /var/lib/apt/lists/ \
&& rm -rf /root/.cache/*
