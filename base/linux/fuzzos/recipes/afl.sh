#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=base/fuzzos/recipes/common.sh
source "${0%/*}/common.sh"

#### AFL

export CC=clang
export CXX=clang++

if is-arm64; then
  export AFL_NO_X86=1
fi

TMPD="$(mktemp -d -p. afl.build.XXXXXXXXXX)"
( cd "$TMPD"
  git-clone "https://github.com/google/AFL"
  ( cd AFL
    make &> /dev/null
    make -C llvm_mode
    make install
  )
)
rm -rf "$TMPD"
