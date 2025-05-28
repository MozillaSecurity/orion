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

case "${1-install}" in
  install)
    apt-install-auto \
      ca-certificates \
      curl \
      gcc \
      git \
      libc6-dev \
      make

    # Build radamsa
    TMPD="$(mktemp -d -p. radamsa.build.XXXXXXXXXX)"
    pushd "$TMPD" >/dev/null
    git-clone https://gitlab.com/akihe/radamsa.git
    cd radamsa
    make
    make install
    popd >/dev/null
    rm -rf "$TMPD"
    ;;
  test)
    radamsa --about
    radamsa --help
    radamsa --version
    ;;
esac
