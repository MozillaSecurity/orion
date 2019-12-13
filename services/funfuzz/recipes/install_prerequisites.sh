#!/bin/bash -ex
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

apt-get update -y -qq
# Required to use apt-key
apt-get install -q -y --no-install-recommends --no-install-suggests dirmngr

apt-key adv --recv-key --keyserver keyserver.ubuntu.com \
    8B48AD6246925553 \
    7638D0442B90D010 \
    04EE7237B7D453EC
echo "deb http://ftp.us.debian.org/debian testing main contrib non-free" >> /etc/apt/sources.list
apt-get update -y -qq

# Prior to deployment, check that apt-get requirements are also installed via other recipes in FuzzOS, e.g. ccache
# Check using `hg --cwd ~/trees/mozilla-central/ diff -r 95ad10e13fb1:0f6958f49842 python/mozboot/mozboot/debian.py`
# Retrieved on 2019-12-12: https://hg.mozilla.org/mozilla-central/file/0f6958f49842/python/mozboot/mozboot/debian.py
apt-get install -q -y --no-install-recommends --no-install-suggests \
    apache2-utils \
    autoconf2.13 \
    build-essential \
    libasound2-dev \
    libcurl4-openssl-dev \
    libdbus-1-dev \
    libdbus-glib-1-dev \
    libgtk-3-dev \
    libgtk2.0-dev \
    libpulse-dev \
    libx11-xcb-dev \
    libxt-dev \
    nasm \
    python-dbus \
    python-dev \
    uuid \
    yasm \
    zip

apt-get install -q -y --no-install-recommends --no-install-suggests \
    libc6-dbg \
    valgrind

apt-get install -q -y --no-install-recommends --no-install-suggests \
    aria2 \
    screen \
    vim
