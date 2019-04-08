#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

#### Bootstrap Packages

apt-get update -qq
apt-get install -y -qq --no-install-recommends --no-install-suggests \
    apt-utils \
    bzip2 \
    curl \
    dbus \
    git \
    gpg-agent \
    locales \
    make \
    nano \
    openssh-client \
    python \
    python-pip \
    python-setuptools \
    python3-pip \
    python3-setuptools \
    software-properties-common \
    unzip \
    xvfb

cd recipes

./fuzzos.sh
./htop.sh
./llvm.sh
./rg.sh
./afl.sh
./fuzzfetch.sh
./credstash.sh
./fuzzmanager.sh
./honggfuzz.sh
./breakpad.sh
./nodejs.sh
./rr.sh
./grcov.sh
./halfempty.sh

./cleanup.sh
