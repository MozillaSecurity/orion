#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

DEBIAN_FRONTEND=noninteractive
export DEBIAN_FRONTEND

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Install recipes

cd "${0%/*}"
./js32_deps.sh  # does the initial sys-update
./htop.sh
./fuzzfetch.sh
./fuzzmanager.sh
./prefpicker.sh
./grcov.sh
./gsutil.sh
./fluentbit.sh
SRCDIR=/tmp/fuzzing-tc ./fuzzing_tc.sh
./llvm-symbolizer.sh
./nodejs.sh
./taskcluster.sh
./worker.sh

packages=(
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
  less
  libglu1-mesa
  libgtk-3-0
  libosmesa6
  libpci3
  locales
  nano
  openssh-client
  pipx
  psmisc
  ripgrep
  screen
  software-properties-common
  subversion
  ubuntu-restricted-addons
  unzip
  wget  # used by oss-fuzz/infra/helper.py
  xvfb
  zip
)

sys-embed "${packages[@]}"
apt-install-depends firefox
apt-get remove --purge -qq xul-ext-ubufox

#### Base System Configuration

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

cat << 'EOF' >> /home/worker/.bashrc

# FuzzOS
export PS1='🐳  \[\033[1;36m\]\h \[\033[1;34m\]\W\[\033[0;35m\] \[\033[1;36m\]λ\[\033[0m\] '
EOF

mkdir -p /home/worker/.local/bin

# Add `cleanup.sh` to let images perform standard cleanup operations.
cp "${0%/*}/cleanup.sh" /home/worker/.local/bin/cleanup.sh

# Add shared `common.sh` to Bash
cp "${0%/*}/common.sh" /home/worker/.local/bin/common.sh
printf "source ~/.local/bin/common.sh\n" >> /home/worker/.bashrc

mkdir -p /src
git init /src/guided-fuzzing-daemon
cd /src/guided-fuzzing-daemon
git remote add origin "https://github.com/MozillaSecurity/guided-fuzzing-daemon"
retry git fetch origin main
git checkout main
cd -
PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin retry pipx install /src/guided-fuzzing-daemon

/home/worker/.local/bin/cleanup.sh

mkdir -p /home/worker/.ssh /root/.ssh
chmod 0700 /home/worker/.ssh /root/.ssh
cat << EOF | tee -a /root/.ssh/config >> /home/worker/.ssh/config
Host *
UseRoaming no
EOF
retry ssh-keyscan github.com | tee -a /root/.ssh/known_hosts >> /home/worker/.ssh/known_hosts

chown -R worker:worker /home/worker
