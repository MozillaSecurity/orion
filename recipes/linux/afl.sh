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

#### AFL

case "${1-install}" in
  install)
    "${0%/*}/llvm.sh"
    apt-install-auto \
      git \
      make

    export CC=clang
    export CXX=clang++

    if is-arm64; then
      export AFL_NO_X86=1
    fi

    TMPD="$(mktemp -d -p. afl.build.XXXXXXXXXX)"
    pushd "$TMPD" >/dev/null
      git-clone "https://github.com/google/AFL"
      cd AFL
      make &> /dev/null
      make -C llvm_mode
      make install
    popd >/dev/null
    rm -rf "$TMPD"
    ;;
  test)
    afl-fuzz -V
    afl-clang --version
    ;;
esac
