#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

#### Base System Configuration

# Generate locales
locale-gen en_US.UTF-8

# Quiet pip
cat << EOF | tee /etc/pip.conf > /dev/null
[global]
disable-pip-version-check = true
no-cache-dir = false

[install]
upgrade-strategy = only-if-needed
EOF

# Ensure the machine uses core dumps with PID in the filename
# https://github.com/moby/moby/issues/11740
cat << EOF | tee /etc/sysctl.d/60-fuzzos.conf > /dev/null
# Ensure that we use PIDs with core dumps
kernel.core_uses_pid = 1
# Allow ptrace of any process
kernel.yama.ptrace_scope = 0
EOF

#### Base Environment Configuration

mkdir ~/.bin

cat << 'EOF' >> ~/.bashrc
# FuzzOS
export PATH=$HOME/.bin:$PATH
EOF

# Add `cleanup.sh` to let images perform standard cleanup operations.
cp "${0%/*}/cleanup.sh" ~/.bin/cleanup.sh

# Add shared `common.sh` to Bash
cp "${0%/*}/common.sh" ~/.common.sh
printf "source ~/.common.sh\n" >> ~/.bashrc
