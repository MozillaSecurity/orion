#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=base/fuzzos/recipes/common.sh
source "${0%/*}/common.sh"

#### Install LLVM

retry curl https://apt.llvm.org/llvm-snapshot.gpg.key | apt-key add -
apt-add-repository "deb https://apt.llvm.org/$(lsb_release -cs)/ llvm-toolchain-$(lsb_release -cs)-8 main"

sys-update
sys-embed \
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
