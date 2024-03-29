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

#### Install gcov-7

case "${1-install}" in
  install)
    apt-install-auto \
      ca-certificates \
      curl \
      gcc-7

    ln -L /usr/bin/gcov-7 /usr/local/bin/gcov-7
    ;;
  test)
    gcov-7 --help
    gcov-7 --version
    ;;
esac
