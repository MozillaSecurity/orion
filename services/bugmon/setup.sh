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
./taskcluster.sh

#### Install packages

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
  python3
  python3-dev
  python3-pip
  python3-setuptools
  python3-venv
  python-is-python3
  software-properties-common
  unzip
  valgrind
  xvfb
)

dbgsym_packages=(
  libcairo2
  libegl1
  libgl1
  libglvnd0
  libglx0
  libgtk-3-0
  libwayland-egl1
)

sys-embed "${packages_with_recommends[@]}"
retry apt-get install -y -qq "${packages[@]}"

# We want full symbols for things GTK/Mesa related where we find crashes.
sys-embed-dbgsym "${dbgsym_packages[@]}"

retry pip3 install \
  psutil \
  virtualenv \
  git+https://github.com/cgoldberg/xvfbwrapper.git


git init bugmon-tc
(
  cd bugmon-tc
  git remote add -t master origin https://github.com/MozillaSecurity/bugmon-tc.git
  retry git fetch -v --depth 1 --no-tags origin master
  git reset --hard FETCH_HEAD
  pip3 install .
)

#### Clean up

./cleanup.sh

#### Create aritfact directory
mkdir /bugmon-artifacts

#### Fix ownership
chown -R worker:worker /bugmon-artifacts
chown -R worker:worker /home/worker
