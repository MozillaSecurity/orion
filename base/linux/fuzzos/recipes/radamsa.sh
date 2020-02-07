#!/bin/bash -ex
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# Build radamsa
TMPD="$(mktemp -d -p. radamsa.build.XXXXXXXXXX)"
( cd "$TMPD"
  git clone --depth 1 --no-tags https://gitlab.com/akihe/radamsa.git
  ( cd radamsa
    CC=clang make
    make install
  )
)
rm -rf "$TMPD"
