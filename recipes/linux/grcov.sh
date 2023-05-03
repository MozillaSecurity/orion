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

#### Install grcov

case "${1-install}" in
  install)
    apt-install-auto \
      ca-certificates \
      cargo

    cargo install --root /usr grcov
    strip /usr/bin/grcov
    ;;
  test)
    grcov --help
    grcov --version
    ;;
esac
