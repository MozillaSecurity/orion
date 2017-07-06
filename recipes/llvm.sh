#!/bin/bash -ex

#### LLVM

curl http://apt.llvm.org/llvm-snapshot.gpg.key | apt-key add -
apt-add-repository "deb http://apt.llvm.org/zesty/ llvm-toolchain-zesty-4.0 main"

apt-get update

apt-get install -y -q --no-install-recommends --no-install-suggests \
  clang-4.0 \
  lldb-4.0 \
  lld-4.0

# update-alternatives --config llvm-config

update-alternatives --install \
  /usr/bin/llvm-config              llvm-config      /usr/bin/llvm-config-4.0  100 \
  --slave /usr/bin/clang            clang            /usr/bin/clang-4.0 \
  --slave /usr/bin/clang++          clang++          /usr/bin/clang++-4.0 \
  --slave /usr/bin/lldb             lldb             /usr/bin/lldb-4.0 \
  --slave /usr/bin/llvm-symbolizer  llvm-symbolizer  /usr/bin/llvm-symbolizer-4.0
