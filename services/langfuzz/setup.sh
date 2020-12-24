#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

function retry () {
  for _ in {1..9}; do
    "$@" && return
    sleep 30
  done
  "$@"
}

retry apt-get update -qq

#### Install fluentbit repo for live-logging to Google Stackdriver

retry apt-get install -y -qq --no-install-recommends \
    ca-certificates \
    curl \
    gpg \
    gpg-agent \
    lsb-release
# these are not needed except to install fluentbit. mark them auto
apt-mark auto gpg gpg-agent lsb-release

curl --retry 5 -sS "https://packages.fluentbit.io/fluentbit.key" | apt-key add -
cat > /etc/apt/sources.list.d/fluentbit.list << EOF
deb https://packages.fluentbit.io/ubuntu/$(lsb_release -sc) $(lsb_release -sc) main
EOF

retry apt-get update -qq

#### Bootstrap Packages

packages=(
  autoconf2.13
  creduce
  g++
  g++-multilib
  gcc-multilib
  gdb
  git
  htop
  jshon
  less
  lib32z1
  lib32z1-dev
  libalgorithm-combinatorics-perl
  libbsd-resource-perl
  libc6-dbg
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
)
retry apt-get install -y -qq --no-install-recommends "${packages[@]}"

# Install fuzzing-tc
# this is used as the entrypoint to intercept stderr/stdout and save it to /logs/live.log
# when run under Taskcluster
retry python3 -m pip install git+https://github.com/MozillaSecurity/fuzzing-tc

# Install taskcluster CLI
TC_VERSION="$(curl --retry 5 -s "https://github.com/taskcluster/taskcluster/releases/latest" | sed 's/.\+\/tag\/\(.\+\)".\+/\1/')"
curl --retry 5 -sSL "https://github.com/taskcluster/taskcluster/releases/download/$TC_VERSION/taskcluster-linux-amd64" -o /usr/local/bin/taskcluster
chmod +x /usr/local/bin/taskcluster

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
rm -rf /usr/share/man/ /usr/share/info/
find /usr/share/doc -depth -type f ! -name copyright -exec rm {} +
find /usr/share/doc -empty -exec rmdir {} +
apt-get clean -y
apt-get autoremove --purge -y
rm -rf /var/lib/apt/lists/*
rm -rf /var/log/*
rm -rf /root/.cache/*
rm -rf /tmp/*

mkdir -p /home/ubuntu/.ssh /root/.ssh
chmod 0700 /home/ubuntu/.ssh /root/.ssh
cat << EOF | tee -a /root/.ssh/config >> /home/ubuntu/.ssh/config
Host *
UseRoaming no
IdentitiesOnly yes
EOF
retry ssh-keyscan github.com | tee -a /root/.ssh/known_hosts >> /home/ubuntu/.ssh/known_hosts

chown -R ubuntu:ubuntu /home/ubuntu
