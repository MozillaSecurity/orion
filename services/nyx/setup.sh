#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

# Fix some packages
# ref: https://github.com/moby/moby/issues/1024
dpkg-divert --local --rename --add /sbin/initctl
ln -sf /bin/true /sbin/initctl

export DEBIAN_FRONTEND="noninteractive"

# Add unprivileged user
useradd --create-home --home-dir /home/worker --shell /bin/bash worker

pkgs=(
  ca-certificates
  curl
  gcc
  git
  jshon
  libasound2
  libblocksruntime0
  libfontconfig1
  libfreetype6
  libglib2.0-0
  libgtk-3-0
  libjpeg-turbo8
  libpixman-1-0
  libpng16-16
  libx11-6
  libx11-xcb1
  libxcomposite1
  libxdamage1
  libxext6
  libxfixes3
  libxml2
  libxrandr2
  make
  netcat-openbsd
  openssh-client
  psmisc
  python3
  xvfb
  zstd
)

sys-update
sys-embed "${pkgs[@]}"
apt-install-auto pipx

mkdir -p /root/.ssh /home/worker/.ssh /home/worker/.local/bin /srv/repos
retry ssh-keyscan github.com | tee -a /root/.ssh/known_hosts /home/worker/.ssh/known_hosts > /dev/null

DESTDIR=/srv/repos EDIT=1 "${0%/*}/fuzzfetch.sh"
DESTDIR=/srv/repos EDIT=1 "${0%/*}/prefpicker.sh"
DESTDIR=/srv/repos EDIT=1 "${0%/*}/fuzzmanager.sh"
SRCDIR=/srv/repos/fuzzing-decision "${0%/*}/fuzzing_tc.sh"
"${0%/*}/fluentbit.sh"
"${0%/*}/taskcluster.sh"
export SKIP_PROFILE=1
source "${0%/*}/clang.sh"

mkdir -p /srv/repos/ipc-research
chown -R worker:worker /home/worker /srv/repos/ipc-research

pushd /srv/repos >/dev/null
git-clone https://github.com/MozillaSecurity/guided-fuzzing-daemon
PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin retry pipx install -e ./guided-fuzzing-daemon
PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin retry pipx inject --include-apps -e guided-fuzzing-daemon ./nyx_ipc_manager
popd >/dev/null

rm -rf /opt/clang /opt/rustc
/srv/repos/setup/cleanup.sh
