#!/bin/bash -ex

echo "en_US.UTF-8 UTF-8" > /etc/locale.gen
locale-gen en_US.UTF-8

apt-get update -y -qq
# Required to use apt-key
apt-get install -q -y --no-install-recommends --no-install-suggests dirmngr

apt-key adv --keyserver keyserver.ubuntu.com --recv-keys 8B48AD6246925553
echo "deb http://ftp.us.debian.org/debian testing main contrib non-free" >> /etc/apt/sources.list

apt-get update -y -qq

# Prior to deployment, check that apt-get requirements are also installed via other recipes in FuzzOS, e.g. ccache
# Check using `hg --cwd ~/trees/mozilla-central/ diff -r edf1f05e9d00:ad6f51d4af0b python/mozboot/mozboot/debian.py`
# Retrieved on 2018-12-26: https://hg.mozilla.org/mozilla-central/file/ad6f51d4af0b/python/mozboot/mozboot/debian.py
apt-get install -q -y --no-install-recommends --no-install-suggests \
    apache2-utils \
    autoconf2.13 \
    build-essential \
    libasound2-dev \
    libcurl4-openssl-dev \
    libdbus-1-dev \
    libdbus-glib-1-dev \
    libgconf2-dev \
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
    lib32z1 \
    libc6-dbg \
    valgrind

apt-get install -q -y --no-install-recommends --no-install-suggests \
    aria2 \
    screen \
    sudo \
    vim

rm -rf /usr/share/man/ /usr/share/info/

find /usr/share/doc -depth -type f ! -name copyright -exec rm {} + || true
find /usr/share/doc -empty -exec rmdir {} + || true

apt-get clean -y
apt-get autoclean -y
apt-get autoremove -y

rm -rf /var/lib/apt/lists/*
rm -rf /root/.cache/*
