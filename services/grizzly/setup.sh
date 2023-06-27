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
./ff32_deps.sh
./fluentbit.sh
./fuzzfetch.sh
EDIT=1 SRCDIR=/src/fuzzing-tc ./fuzzing_tc.sh
EDIT=1 DESTDIR=/src ./fuzzmanager.sh
./grcov.sh
./nodejs.sh
./radamsa.sh
./redis.sh
./rr.sh
./gcov-9.sh
./taskcluster.sh

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
  libpulse0
  p7zip-full
  python3-wheel
  screen
  subversion
  ubuntu-desktop-minimal
  ubuntu-restricted-addons
  wget
  zip
  zstd
)

# packages with *unwanted* recommends
packages_with_recommends=(
  bzip2
  curl
  dbus
  g++
  gcc
  gdb
  git
  gpg-agent
  jshon
  less
  libavcodec-extra
  libc6-dev
  libgtk-3-0
  locales
  make
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
  libegl-mesa0
  libgl1
  libglib2.0-0
  libgl1-mesa-dri
  libglapi-mesa
  libglu1-mesa
  libglvnd0
  libglx-mesa0
  libglx0
# 2023-06-27: disabled because temporarily missing from dbgsym repo
#  libgtk-3-0
  libosmesa6
# 2023-06-27: disabled because temporarily missing from dbgsym repo
#  libwayland-egl1
  mesa-va-drivers
  mesa-vdpau-drivers
  mesa-vulkan-drivers
)

sys-embed "${packages_with_recommends[@]}"
retry apt-get install -y -qq "${packages[@]}"
apt-get remove -y gvfs  # see https://bugzilla.mozilla.org/show_bug.cgi?id=1682934

# We want full symbols for things GTK/Mesa related where we find crashes.
sys-embed-dbgsym "${dbgsym_packages[@]}"

retry pip3 install \
  /src/rwait \
  psutil \
  virtualenv \
  git+https://github.com/cgoldberg/xvfbwrapper.git

#### Base System Configuration

# Generate locales
locale-gen en_US.utf8

# Ensure we retry metadata requests in case of glitches
# https://github.com/boto/boto/issues/1868
cat << EOF > /etc/boto.cfg
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
cat << EOF | tee -a /root/.ssh/config /home/worker/.ssh/config > /dev/null
Host *
UseRoaming no
EOF
retry ssh-keyscan github.com | tee -a /root/.ssh/known_hosts /home/worker/.ssh/known_hosts > /dev/null

# get new minidump-stackwalk
retry-curl "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.cache.level-3.toolchains.v3.linux64-minidump-stackwalk.latest/artifacts/public/build/minidump-stackwalk.tar.zst" | zstdcat | tar xv --strip 1 -C "/usr/local/bin"
/usr/local/bin/minidump-stackwalk --version

chown -R worker:worker /home/worker /src
chmod 0777 /src
