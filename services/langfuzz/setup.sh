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

EDIT=1 DESTDIR=/src ./fuzzmanager.sh
./fuzzfetch.sh
./grcov.sh
if ! is-arm64; then
./llvm-symbolizer.sh
fi
./taskcluster.sh

# use Amazon Corretto OpenJDK
retry-curl https://apt.corretto.aws/corretto.key | gpg --dearmor -o /etc/apt/keyrings/corretto.gpg
echo "deb [signed-by=/etc/apt/keyrings/corretto.gpg] https://apt.corretto.aws stable main" > /etc/apt/sources.list.d/corretto.list
sys-update

# setup maven
mkdir /opt/maven
retry-curl https://dlcdn.apache.org/maven/maven-3/3.9.9/binaries/apache-maven-3.9.9-bin.tar.gz | tar -C /opt/maven --strip-components=1 -xz
echo "PATH=\$PATH:/opt/maven/bin" >> /etc/bash.bashrc

#### Bootstrap Packages

packages=(
  autoconf2.13
  ca-certificates
  curl
  creduce
  g++
  gdb
  git
  htop
  java-11-amazon-corretto-jdk
  jshon
  lbzip2
  less
  libalgorithm-combinatorics-perl
  libbsd-resource-perl
  libc6-dbg
  libio-prompt-perl
  libnspr4
  libwww-mechanize-perl
  locales
  mailutils
  mercurial
  nano
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

# Add 32 bit packages for x86-64 (unavailable for arm64)
if ! is-arm64; then
  packages+=(
    lib32z1
    lib32z1-dev
    libc6-dbg:i386
    g++-multilib
    gcc-multilib
  )
else
  # install llvm for llvm-symbolizer on arm64
  packages+=(llvm-15)
fi

retry apt-get install -y -qq --no-install-recommends "${packages[@]}"

if is-arm64; then
  update-alternatives --install \
    /usr/bin/llvm-config              llvm-config      /usr/bin/llvm-config-15     100 \
    --slave /usr/bin/llvm-symbolizer  llvm-symbolizer  /usr/bin/llvm-symbolizer-15
fi

python_packages=(
  google-cloud-storage
  jsbeautifier
)

retry pip3 install "${python_packages[@]}"

# use gcov-9
./gcov-9.sh
mv /usr/local/bin/gcov-9 /usr/local/bin/gcov
rm /usr/bin/gcov

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
