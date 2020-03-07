#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Install LLVM

if [ "$1" = "auto" ]; then
  function install-auto-arg () {
    apt-install-auto "$@"
  }
else
  function install-auto-arg () {
    sys-embed "$@"
  }
fi

apt-install-auto \
  ca-certificates \
  curl \
  software-properties-common \
  gpg \
  gpg-agent

if ! grep -q "llvm-toolchain-$(lsb_release -cs)-8" /etc/apt/sources.list; then
  curl -sL --retry 5 https://apt.llvm.org/llvm-snapshot.gpg.key | apt-key add -
  apt-add-repository "deb https://apt.llvm.org/$(lsb_release -cs)/ llvm-toolchain-$(lsb_release -cs)-8 main"
  rm -f /etc/apt/sources.list.save
  sys-update
fi

install-auto-arg \
  clang-8 \
  lld-8 \
  lldb-8 \
  libfuzzer-8-dev \
  libc++-8-dev libc++abi-8-dev

update-alternatives --install \
  /usr/bin/llvm-config              llvm-config      /usr/bin/llvm-config-8     100 \
  --slave /usr/bin/clang            clang            /usr/bin/clang-8               \
  --slave /usr/bin/clang++          clang++          /usr/bin/clang++-8             \
  --slave /usr/bin/llvm-symbolizer  llvm-symbolizer  /usr/bin/llvm-symbolizer-8     \
  --slave /usr/bin/lldb             lldb             /usr/bin/lldb-8
