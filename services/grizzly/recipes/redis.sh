#!/bin/bash -ex
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

apt-get install -q -y \
    redis-server

apt-get install -q -y --no-install-recommends \
    python-hiredis

sed -i 's/^bind .*/bind 127.0.0.1/' /etc/redis/redis.conf
