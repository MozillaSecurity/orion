#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

# shellcheck source=recipes/linux/common.sh
source ./common.sh
# shellcheck source=recipes/linux/taskgraph-m-c-latest.sh
source ./taskgraph-m-c-latest.sh

# Fix some packages
# ref: https://github.com/moby/moby/issues/1024
dpkg-divert --local --rename --add /sbin/initctl
ln -sf /bin/true /sbin/initctl

export DEBIAN_FRONTEND=noninteractive

./js32_deps.sh # does the initial sys-update
./grcov.sh
./gsutil.sh
./fluentbit.sh
SRCDIR=/srv/repos/fuzzing-decision ./fuzzing_tc.sh
./llvm-symbolizer.sh
./nodejs.sh
./sentry.sh
./taskcluster.sh
./worker.sh

pkgs=(
  apt-utils
  binutils
  bzip2
  chromium-codecs-ffmpeg-extra
  curl
  git
  gpg-agent
  gstreamer1.0-gl
  gstreamer1.0-libav
  gstreamer1.0-plugins-base
  gstreamer1.0-plugins-ugly
  gstreamer1.0-vaapi
  jshon
  lbzip2
  libglu1-mesa
  libgtk-3-0
  libosmesa6
  libpci3
  openssh-client
  patch
  pipx
  psmisc
  ripgrep
  screen
  software-properties-common
  ubuntu-restricted-addons
  unzip
  wget # used by oss-fuzz/infra/helper.py
  xvfb
  zip
  zstd
)

sys-update
sys-embed "${pkgs[@]}"
apt-install-depends firefox
apt-mark auto xul-ext-ubufox

mkdir -p /root/.ssh /home/worker/.ssh /home/worker/.local/bin
retry ssh-keyscan github.com | tee -a /root/.ssh/known_hosts /home/worker/.ssh/known_hosts >/dev/null

DESTDIR=/srv/repos EDIT=1 ./fuzzmanager.sh
DESTDIR=/srv/repos EDIT=1 ./fuzzfetch.sh
DESTDIR=/srv/repos EDIT=1 ./prefpicker.sh

chown -R worker:worker /home/worker /srv/repos

afl_ver="$(resolve-tc-alias afl-instrumentation)"
retry-curl "$(resolve-tc "$afl_ver")" | zstdcat | tar -x -C /opt
# shellcheck disable=SC2016
echo 'PATH=$PATH:/opt/afl-instrumentation/bin' >>/etc/bash.bashrc
pushd /opt/afl-instrumentation/bin
patch -p1 </home/worker/patches/afl-cmin.diff
popd >/dev/null

cd ..
su worker <<EOF
source ./setup/common.sh
git-clone "https://github.com/MozillaSecurity/guided-fuzzing-daemon"
EOF

PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin retry pipx install -e ./guided-fuzzing-daemon
PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin retry pipx inject --include-apps -e guided-fuzzing-daemon ./nyx_utils

/srv/repos/setup/cleanup.sh
