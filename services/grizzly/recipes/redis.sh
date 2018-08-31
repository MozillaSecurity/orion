#!/bin/bash -ex

apt-get install -q -y \
    redis-server

apt-get install -q -y --no-install-recommends \
    python-hiredis

sed -i 's/^bind .*/bind 127.0.0.1/' /etc/redis/redis.conf
