#!/bin/bash -ex

#### Honggfuzz

. ./recipes/common.sh

apt-get install -y -qq --no-install-recommends --no-install-suggests \
    libunwind8 \
    libbinutils \
    libblocksruntime0
apt-install-auto \
  libunwind-dev \
  binutils-dev \
  libblocksruntime-dev

TMPD="$(mktemp -d -p. honggfuzz.build.XXXXXXXXXX)"
( cd "$TMPD"
  git clone --depth 1 --no-tags https://github.com/google/honggfuzz.git
  ( cd honggfuzz
    CC=clang make
    install honggfuzz /usr/local/bin/
    install hfuzz_cc/hfuzz-cc /usr/local/bin/
    install hfuzz_cc/hfuzz-g* /usr/local/bin/
    install hfuzz_cc/hfuzz-clang* /usr/local/bin/
  )
)
rm -rf "$TMPD"
