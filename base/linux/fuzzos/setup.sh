#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=recipes/linux/common.sh
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

#### Base System Configuration

# Generate locales
locale-gen en_US.utf8

# Ensure the machine uses core dumps with PID in the filename
# https://github.com/moby/moby/issues/11740
cat << EOF | tee /etc/sysctl.d/60-fuzzos.conf > /dev/null
# Ensure that we use PIDs with core dumps
kernel.core_uses_pid = 1
# Allow ptrace of any process
kernel.yama.ptrace_scope = 0
EOF

# Ensure we retry metadata requests in case of glitches
# https://github.com/boto/boto/issues/1868
cat << EOF | tee /etc/boto.cfg > /dev/null
[Boto]
metadata_service_num_attempts = 10
EOF

#### Base Environment Configuration

cat<< 'EOF' >> ~/.bashrc

# FuzzOS
export PS1='🐳  \[\033[1;36m\]\h \[\033[1;34m\]\W\[\033[0;35m\] \[\033[1;36m\]λ\[\033[0m\] '
EOF

mkdir -p ~/.local/bin

# Add `cleanup.sh` to let images perform standard cleanup operations.
cp "${0%/*}/cleanup.sh" ~/.local/bin/cleanup.sh

# Add shared `common.sh` to Bash
cp "${0%/*}/common.sh" ~/.local/bin/common.sh
printf "source ~/.local/bin/common.sh\n" >> ~/.bashrc

#### Install recipes

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
