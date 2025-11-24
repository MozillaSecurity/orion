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
SRCDIR=/srv/repos/fuzzing-decision ./fuzzing_tc.sh

./grcov.sh
./llvm-cov.sh
./llvm-symbolizer.sh
./sentry.sh
./taskcluster.sh

#### Bootstrap Packages

packages=(
  binutils
  ca-certificates
  curl
  gdb
  git
  jshon
  lbzip2
  less
  libc6-dbg
  libc6-dev
  libgcc-11-dev
  locales
  openssh-client
  pipx
  psmisc
  rsync
  screen
  software-properties-common
  td-agent-bit
  unzip
  zip
  zstd
)
if ! is-arm64; then
  packages+=(
    libc6-dbg:i386
  )
fi
retry apt-get install -y -qq --no-install-recommends "${packages[@]}"

# Install swift
retry-curl "https://download.swift.org/swiftly/linux/swiftly-$(uname -m).tar.gz" | tar xz
mv swiftly /home/ubuntu/
chmod 755 /home/ubuntu/swiftly
su - ubuntu -c "/home/ubuntu/swiftly init --quiet-shell-followup -y"
echo ". /home/ubuntu/.local/share/swiftly/env.sh" >>/home/ubuntu/.bashrc

#### Base System Configuration

# Generate locales
locale-gen en_US.utf8

# Ensure we retry metadata requests in case of glitches
# https://github.com/boto/boto/issues/1868
cat <<EOF | tee /etc/boto.cfg >/dev/null
[Boto]
metadata_service_num_attempts = 10
EOF

#### Base Environment Configuration

cat <<'EOF' >>/home/ubuntu/.bashrc

# FuzzOS
export PS1='🐳  \[\033[1;36m\]\h \[\033[1;34m\]\W\[\033[0;35m\] \[\033[1;36m\]λ\[\033[0m\] '
EOF

mkdir -p /home/ubuntu/.local/bin

# Add shared `common.sh` to Bash
cp "${0%/*}/common.sh" /home/ubuntu/.local/bin/common.sh
printf "source ~/.local/bin/common.sh\n" >>/home/ubuntu/.bashrc

mkdir -p /home/ubuntu/.ssh /root/.ssh
chmod 0700 /home/ubuntu/.ssh /root/.ssh
cat <<EOF | tee -a /root/.ssh/config /home/ubuntu/.ssh/config
Host *
UseRoaming no
IdentitiesOnly yes
EOF
retry ssh-keyscan github.com | tee -a /root/.ssh/known_hosts /home/ubuntu/.ssh/known_hosts

DESTDIR=/srv/repos EDIT=1 ./fuzzmanager.sh
PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin retry pipx inject fuzzmanager boto
DESTDIR=/srv/repos EDIT=1 ./fuzzfetch.sh

chown -R ubuntu:ubuntu /home/ubuntu /srv/repos

cd ..
su ubuntu <<EOF
source ./setup/common.sh
git-clone "https://github.com/MozillaSecurity/guided-fuzzing-daemon"
EOF

PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin retry pipx install -e ./guided-fuzzing-daemon[sentry]

# Cleanup
"${0%/*}/cleanup.sh"
