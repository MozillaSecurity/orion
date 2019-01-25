#!/usr/bin/env bash

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

./cleanup.sh
