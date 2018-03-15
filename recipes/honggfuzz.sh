#!/bin/sh -ex

#### Honggfuzz

cd "$HOME"

apt-get install -y -qq --no-install-recommends --no-install-suggests \
  libunwind-dev \
  binutils-dev \
  libblocksruntime-dev

git clone --depth=1 https://github.com/google/honggfuzz.git
(cd honggfuzz && make)
cp honggfuzz/honggfuzz /usr/local/bin/
