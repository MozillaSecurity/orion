#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=base/linux/fuzzos/recipes/common.sh
source ~/.common.sh

sys-embed redis-server python3-hiredis

sed -i 's/^bind .*/bind 127.0.0.1/' /etc/redis/redis.conf
