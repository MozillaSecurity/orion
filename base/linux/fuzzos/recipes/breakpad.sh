#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=base/fuzzos/recipes/common.sh
source "${0%/*}/common.sh"

#### Install Breakpad Tools

TMPD="$(mktemp -d -p. breakpad.tools.XXXXXXXXXX)"
( cd "$TMPD"
  git-clone "https://github.com/google/breakpad"
  cd breakpad
  git-clone "https://chromium.googlesource.com/linux-syscall-support" src/third_party/lss
  ./configure
  make
  make install
)
rm -rf "$TMPD"
