#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=base/linux/fuzzos/recipes/common.sh
source "${0%/*}/common.sh"

#### Install Honggfuzz

sys-embed \
  libunwind8 \
  libbinutils \
  libblocksruntime0

apt-install-auto \
  libunwind-dev \
  binutils-dev \
  libblocksruntime-dev

TMPD="$(mktemp -d -p. honggfuzz.build.XXXXXXXXXX)"
( cd "$TMPD"
  git clone --depth 1 --no-tags https://github.com/google/honggfuzz.git
  ( cd honggfuzz
    CC=clang make
    install honggfuzz /usr/local/bin/
    install hfuzz_cc/hfuzz-cc /usr/local/bin/
    install hfuzz_cc/hfuzz-g* /usr/local/bin/
    install hfuzz_cc/hfuzz-clang* /usr/local/bin/
  )
)
rm -rf "$TMPD"
