#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Install recipes

cd "${0%/*}"

# also does the initial sys-update
./js32_deps.sh

# for live-logging to Google Stackdriver
./fluentbit.sh

# this is used as the entrypoint to intercept stderr/stdout and save it to /logs/live.log
# when run under Taskcluster
EDIT=1 SRCDIR=/src/fuzzing-tc ./fuzzing_tc.sh

./fuzzfetch.sh
./taskcluster.sh
./fuzzmanager.sh
./grcov.sh
./llvm-symbolizer.sh

#### Bootstrap Packages

packages=(
  autoconf2.13
  ca-certificates
  curl
  creduce
  g++
  g++-multilib
  gcc-multilib
  gdb
  git
  htop
  jshon
  lbzip2
  less
  lib32z1
  lib32z1-dev
  libalgorithm-combinatorics-perl
  libbsd-resource-perl
  libc6-dbg
  libc6-dbg:i386
  libio-prompt-perl
  libwww-mechanize-perl
  locales
  mailutils
  maven
  mercurial
  nano
  openjdk-8-jdk
  openssh-client
  psmisc
  python-is-python3
  python3-dev
  python3-pip
  python3-setuptools
  python3-wheel
  screen
  software-properties-common
  td-agent-bit
  unzip
  valgrind
  vim
  zip
  zstd
)
retry apt-get install -y -qq --no-install-recommends "${packages[@]}"

# Install swift
retry-curl https://download.swift.org/swift-5.10-release/ubuntu2004/swift-5.10-RELEASE/swift-5.10-RELEASE-ubuntu20.04.tar.gz | tar -xz
mv swift-5* /opt/swift5

echo "export PATH=/opt/swift5/usr/bin:$PATH" >> /home/ubuntu/.bashrc

#### Base System Configuration

# Generate locales
locale-gen en_US.utf8

# Ensure we retry metadata requests in case of glitches
# https://github.com/boto/boto/issues/1868
cat << EOF | tee /etc/boto.cfg > /dev/null
[Boto]
metadata_service_num_attempts = 10
EOF

#### Base Environment Configuration

cat << 'EOF' >> /home/ubuntu/.bashrc

# FuzzOS
export PS1='🐳  \[\033[1;36m\]\h \[\033[1;34m\]\W\[\033[0;35m\] \[\033[1;36m\]λ\[\033[0m\] '
EOF

mkdir -p /home/ubuntu/.local/bin

# Add shared `common.sh` to Bash
cp "${0%/*}/common.sh" /home/ubuntu/.local/bin/common.sh
printf "source ~/.local/bin/common.sh\n" >> /home/ubuntu/.bashrc

# Cleanup
"${0%/*}/cleanup.sh"

mkdir -p /home/ubuntu/.ssh /root/.ssh
chmod 0700 /home/ubuntu/.ssh /root/.ssh
cat << EOF | tee -a /root/.ssh/config /home/ubuntu/.ssh/config
Host *
UseRoaming no
IdentitiesOnly yes
EOF
retry ssh-keyscan github.com | tee -a /root/.ssh/known_hosts /home/ubuntu/.ssh/known_hosts

chown -R ubuntu:ubuntu /home/ubuntu
