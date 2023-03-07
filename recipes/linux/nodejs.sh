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

#### Install NodeJS

case "${1-install}" in
  install)
    apt-install-auto \
      binutils \
      ca-certificates \
      curl

    retry-curl https://deb.nodesource.com/setup_18.x | bash -
    sys-embed nodejs
    strip --strip-unneeded /usr/bin/node
    ;;
  test)
    node --help
    node --version
    npm --version
    ;;
esac
