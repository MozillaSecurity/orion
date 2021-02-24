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

#### Install gcov-9

case "${1-install}" in
  install)
    apt-install-auto \
      ca-certificates \
      curl \
      gcc-9

    ln -L /usr/bin/gcov-9 /usr/local/bin/gcov-9
    ;;
  test)
    gcov-9 --help
    gcov-9 --version
    ;;
esac
