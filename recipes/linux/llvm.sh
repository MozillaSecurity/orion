#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# supports-test

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Install LLVM

VERSION=12

if [ "$1" = "auto" ]; then
  function install-auto-arg () {
    apt-install-auto "$@"
  }
  shift
else
  function install-auto-arg () {
    sys-embed "$@"
  }
fi

case "${1-install}" in
  install)
    apt-install-auto \
      ca-certificates \
      curl \
      software-properties-common \
      gpg \
      gpg-agent

    if ! grep -q "llvm-toolchain-$(lsb_release -cs)-$VERSION" /etc/apt/sources.list; then
      curl -sL --retry 5 https://apt.llvm.org/llvm-snapshot.gpg.key | apt-key add -
      apt-add-repository "deb https://apt.llvm.org/$(lsb_release -cs)/ llvm-toolchain-$(lsb_release -cs)-$VERSION main"
      rm -f /etc/apt/sources.list.save
      sys-update
    fi

    install-auto-arg \
      "clang-$VERSION" \
      "lld-$VERSION" \
      "lldb-$VERSION" \
      "libfuzzer-$VERSION-dev" \
      "libc++-$VERSION-dev" "libc++abi-$VERSION-dev"

    update-alternatives --install \
      /usr/bin/llvm-config              llvm-config      /usr/bin/llvm-config-$VERSION     100 \
      --slave /usr/bin/clang            clang            /usr/bin/clang-$VERSION               \
      --slave /usr/bin/clang++          clang++          /usr/bin/clang++-$VERSION             \
      --slave /usr/bin/llvm-symbolizer  llvm-symbolizer  /usr/bin/llvm-symbolizer-$VERSION     \
      --slave /usr/bin/lldb             lldb             /usr/bin/lldb-$VERSION
    ;;
  test)
    clang --version
    llvm-symbolizer --version
    ;;
esac
