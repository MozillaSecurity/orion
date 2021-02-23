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
    sys-embed redis-server python3-hiredis

    sed -i 's/^bind .*/bind 127.0.0.1/' /etc/redis/redis.conf
    ;;
  test)
    redis-server --version
    redis-cli --version
    python3 -c "import hiredis"
    ;;
esac
