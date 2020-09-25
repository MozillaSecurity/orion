#!/bin/bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Bootstrap Packages

sys-update

#### Install recipes

cd "${0%/*}"
./berglas.sh
./breakpad.sh
./credstash.sh
./fluentbit.sh
./fuzzfetch.sh
./fuzzing_tc.sh
./fuzzmanager.sh
./grcov.sh
./htop.sh
./nodejs.sh
./radamsa.sh
./redis.sh
./rg.sh
./rr.sh
./gcov-7.sh
./gcov-8.sh

# shellcheck source=recipes/linux/dbgsyms.sh
source ./dbgsyms.sh

# packages without recommends (or *wanted* recommends)
# TODO: we should expand recommends and just have one list
packages=(
  libasound2
  libc6-dbg
  libdbus-glib-1-2
  libglu1-mesa
  libosmesa6
  pulseaudio
  python3-wheel
  screen
  subversion
  ubuntu-desktop-minimal
  ubuntu-restricted-addons
  wget
  zip
)

# packages with *unwanted* recommends
packages_with_recommends=(
  apt-utils
  build-essential
  bzip2
  curl
  dbus
  gdb
  git
  gpg-agent
  jshon
  less
  libavcodec-extra
  libgtk-3-0
  locales
  nano
  openssh-client
  python3-pip
  python3-setuptools
  python3-venv
  software-properties-common
  unzip
  valgrind
  xvfb
)

dbgsym_packages=(
  libcairo2
  libegl1
#  libegl-mesa0
  libgl1
#  libgl1-mesa-dri
#  libglapi-mesa
#  libglu1-mesa
  libglvnd0
#  libglx-mesa0
  libglx0
  libgtk-3-0
#  libosmesa6
  libwayland-egl1
#  mesa-va-drivers
#  mesa-vdpau-drivers
)

sys-embed "${packages_with_recommends[@]}"
retry apt-get install -y -qq "${packages[@]}"

# We want full symbols for things GTK/Mesa related where we find crashes.
sys-embed-dbgsym "${dbgsym_packages[@]}"

retry pip3 install \
  psutil \
  virtualenv \
  git+https://github.com/cgoldberg/xvfbwrapper.git

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

/home/worker/.local/bin/cleanup.sh

mkdir -p /home/worker/.ssh /root/.ssh
chmod 0700 /home/worker/.ssh /root/.ssh
cat << EOF | tee -a /root/.ssh/config >> /home/worker/.ssh/config
Host *
UseRoaming no
EOF
retry ssh-keyscan github.com | tee -a /root/.ssh/known_hosts >> /home/worker/.ssh/known_hosts

chown -R worker:worker /home/worker
