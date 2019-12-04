#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=base/linux/fuzzos/recipes/common.sh
source "${0%/*}/common.sh"

#### Install rr

apt-install-auto \
  ccache \
  cmake \
  make \
  g++-multilib \
  gdb \
  pkg-config \
  coreutils \
  python-pexpect \
  manpages-dev \
  ninja-build

apt-get install -q -y \
  capnproto \
  libcapnp-dev

pip3 install pexpect

TMPD="$(mktemp -d -p. rr.build.XXXXXXXXXX)"
( cd "$TMPD"
  git clone --depth 1 --no-tags https://github.com/mozilla/rr.git
  ( cd rr
    PATCH="git.$(git log -1 --date=iso | grep -o '[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}' | tr -d '-').$(git rev-parse --short HEAD)"
    sed -i "s/set(rr_VERSION_PATCH [0-9]\\+)/set(rr_VERSION_PATCH $PATCH)/" CMakeLists.txt
  )
  mkdir obj
  ( cd obj
    CC=clang CXX=clang++ cmake -G Ninja ../rr
    cmake --build .
    cpack -G DEB
    dpkg -i dist/rr-*.deb
  )
)
rm -rf "$TMPD"
