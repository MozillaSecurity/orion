#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

#### AFL

TMPD="$(mktemp -d -p. afl.build.XXXXXXXXXX)"
( cd "$TMPD"
  git clone -v --depth 1 --no-tags https://github.com/choller/afl.git
  ( cd afl
    make
    # Disabled due to SIGSEGV in Clang > 6.
    # Read https://bugs.llvm.org/show_bug.cgi?id=39321 for possible workarounds.
    # make -C llvm_mode
    make install
  )
)
rm -rf "$TMPD"
