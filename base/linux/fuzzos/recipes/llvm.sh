#!/usr/bin/env bash

set -e
set -x

#### Install LLVM

curl https://apt.llvm.org/llvm-snapshot.gpg.key | apt-key add -
apt-add-repository "deb https://apt.llvm.org/$(lsb_release -cs)/ llvm-toolchain-$(lsb_release -cs)-6.0 main"

apt-get update -qq
apt-get install -y -qq --no-install-recommends --no-install-suggests \
  clang-6.0 \
  lld-6.0 \
  lldb-6.0

update-alternatives --install \
  /usr/bin/llvm-config              llvm-config      /usr/bin/llvm-config-6.0     100 \
  --slave /usr/bin/clang            clang            /usr/bin/clang-6.0               \
  --slave /usr/bin/clang++          clang++          /usr/bin/clang++-6.0             \
  --slave /usr/bin/llvm-symbolizer  llvm-symbolizer  /usr/bin/llvm-symbolizer-6.0     \
  --slave /usr/bin/lldb             lldb             /usr/bin/lldb-6.0
