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

#### Install Breakpad Tools

case "${1-install}" in
  install)
    "${0%/*}/llvm.sh" auto
    apt-install-auto \
      git \
      make

    export CC=clang
    export CXX=clang++

    TMPD="$(mktemp -d -p. breakpad.tools.XXXXXXXXXX)"
    pushd "$TMPD" >/dev/null
      git-clone "https://github.com/google/breakpad"
      cd breakpad
      git-clone "https://chromium.googlesource.com/linux-syscall-support" src/third_party/lss
      ./configure
      make
      make install
    popd >/dev/null
    rm -rf "$TMPD"
    ;;
  test)
    set +e
    minidump_stackwalk
    if [[ $? -ne 1 ]]
    then
      exit 1
    fi
    set -e
    ;;
esac
