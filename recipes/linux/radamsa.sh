#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

# wget is used in the make process
apt-install-auto \
    ca-certificates \
    gcc \
    git \
    libc6-dev \
    make \
    wget

# Build radamsa
TMPD="$(mktemp -d -p. radamsa.build.XXXXXXXXXX)"
( cd "$TMPD"
  git-clone https://gitlab.com/akihe/radamsa.git
  ( cd radamsa
    make
    make install
  )
)
rm -rf "$TMPD"
