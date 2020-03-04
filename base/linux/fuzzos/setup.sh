#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=base/linux/fuzzos/recipes/common.sh
source "${0%/*}/recipes/common.sh"

#### Bootstrap Packages

sys-update
sys-embed \
    apt-utils \
    bzip2 \
    curl \
    dbus \
    git \
    gpg-agent \
    jshon \
    jq \
    locales \
    less \
    make \
    nano \
    openssh-client \
    python \
    python-pip \
    python-setuptools \
    python3-pip \
    python3-dev \
    python3-setuptools \
    python3-venv \
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
./berglas.sh
./gsutil.sh
./radamsa.sh
./remote_syslog.sh

./cleanup.sh
