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

#### Install gcov-8

case "${1-install}" in
  install)
    apt-install-auto \
      ca-certificates \
      curl \
      gcc-8

    ln -L /usr/bin/gcov-8 /usr/local/bin/gcov-8
    ;;
  test)
    gcov-8 --help
    gcov-8 --version
    ;;
esac
