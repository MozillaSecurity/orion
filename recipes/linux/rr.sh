#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Install rr

if is-arm64; then
  echo "[INFO] rr is currently not supported on any ARM architecture."
  exit
fi

"${0%/*}/llvm.sh" auto
apt-install-auto \
  capnproto \
  cmake \
  file \
  g++-multilib \
  gdb \
  git \
  libcapnp-dev \
  ninja-build \
  pkg-config \
  python3-pexpect

export CC=clang
export CXX=clang++

TMPD="$(mktemp -d -p. rr.build.XXXXXXXXXX)"
( cd "$TMPD"
  retry git clone --depth 1 --no-tags https://github.com/mozilla/rr.git
  ( cd rr
    PATCH="git.$(git log -1 --date=iso | grep -o '[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}' | tr -d '-').$(git rev-parse --short HEAD)"
    sed -i "s/set(rr_VERSION_PATCH [0-9]\\+)/set(rr_VERSION_PATCH $PATCH)/" CMakeLists.txt
    git apply << EOF
--- a/CMakeLists.txt
+++ b/CMakeLists.txt
@@ -1548,3 +1548,4 @@
+ set(CPACK_DEBIAN_PACKAGE_SHLIBDEPS ON)
 
 include (CPack)
 
EOF
  )
  mkdir obj
  ( cd obj
    CC=clang CXX=clang++ cmake -G Ninja -Dstrip=TRUE ../rr
    cmake --build .
    cpack -G DEB
    dpkg -i dist/rr-*.deb
  )
)
rm -rf "$TMPD"
