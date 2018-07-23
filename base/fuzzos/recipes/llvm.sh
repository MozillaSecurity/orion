#!/bin/bash -ex

#### LLVM

# shellcheck disable=SC1091
. /etc/lsb-release
curl https://apt.llvm.org/llvm-snapshot.gpg.key | apt-key add -
apt-add-repository "deb https://apt.llvm.org/$DISTRIB_CODENAME/ llvm-toolchain-$DISTRIB_CODENAME-5.0 main"
apt-add-repository "deb https://apt.llvm.org/$DISTRIB_CODENAME/ llvm-toolchain-$DISTRIB_CODENAME-6.0 main"

apt-get update -qq

apt-get install -y -qq --no-install-recommends --no-install-suggests \
  clang-5.0 \
  lld-5.0 \
  lldb-5.0 \
  clang-6.0 \
  lld-6.0
# lldb-6.0


# update-alternatives --config llvm-config

update-alternatives --install \
  /usr/bin/llvm-config              llvm-config      /usr/bin/llvm-config-5.0     100 \
  --slave /usr/bin/clang            clang            /usr/bin/clang-5.0               \
  --slave /usr/bin/clang++          clang++          /usr/bin/clang++-5.0             \
  --slave /usr/bin/llvm-symbolizer  llvm-symbolizer  /usr/bin/llvm-symbolizer-5.0     \
  --slave /usr/bin/lldb             lldb             /usr/bin/lldb-5.0

update-alternatives --install \
  /usr/bin/llvm-config              llvm-config      /usr/bin/llvm-config-6.0     100 \
  --slave /usr/bin/clang            clang            /usr/bin/clang-6.0               \
  --slave /usr/bin/clang++          clang++          /usr/bin/clang++-6.0             \
  --slave /usr/bin/llvm-symbolizer  llvm-symbolizer  /usr/bin/llvm-symbolizer-6.0     \
# --slave /usr/bin/lldb             lldb             /usr/bin/lldb-6.0

