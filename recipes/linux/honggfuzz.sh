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

#### Install Honggfuzz

case "${1-install}" in
  install)
    "${0%/*}/llvm.sh"
    sys-embed \
      libbinutils \
      libblocksruntime0 \
      libunwind8
    apt-install-auto \
      binutils-dev \
      git \
      make \
      libblocksruntime-dev \
      libunwind-dev

    TMPD="$(mktemp -d -p. honggfuzz.build.XXXXXXXXXX)"
    pushd "$TMPD" >/dev/null
      git-clone https://github.com/google/honggfuzz
      cd honggfuzz
      CC=clang make
      install honggfuzz /usr/local/bin/
      install hfuzz_cc/hfuzz-cc /usr/local/bin/
      install hfuzz_cc/hfuzz-g* /usr/local/bin/
      install hfuzz_cc/hfuzz-clang* /usr/local/bin/
    popd >/dev/null
    rm -rf "$TMPD"
    ;;
  test)
    honggfuzz --help
    hfuzz-clang --version
    ;;
esac
