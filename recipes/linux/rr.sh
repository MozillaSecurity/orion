#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# supports-test

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Install rr

REVISION=b759bb569c1d1a41ba3ccda9fc34c33ac9fb6c2b

if is-arm64; then
  echo "[INFO] rr is currently not supported on any ARM architecture."
  exit
fi

case "${1-install}" in
  install)
    "${0%/*}/llvm.sh" auto
    apt-install-auto \
      capnproto \
      cmake \
      dpkg-dev \
      file \
      g++-multilib \
      gdb \
      git \
      libcapnp-dev \
      ninja-build \
      pkg-config \
      python3-pexpect \
      zlib1g-dev

    export CC=clang
    export CXX=clang++

    TMPD="$(mktemp -d -p. rr.build.XXXXXXXXXX)"
    pushd "$TMPD" >/dev/null
      git init rr
      pushd rr >/dev/null
        git remote add -t master origin https://github.com/rr-debugger/rr.git
        retry git fetch --no-tags origin "$REVISION"
        git reset --hard "$REVISION"
        PATCH="git.$(git log -1 --date=iso | grep -o '[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}' | tr -d '-').$(git rev-parse --short HEAD)"
        sed -i "s/set(rr_VERSION_PATCH [0-9]\\+)/set(rr_VERSION_PATCH $PATCH)/" CMakeLists.txt
        git apply <<- "EOF"
	diff --git a/CMakeLists.txt b/CMakeLists.txt
	index d0d02346..29ac3b57 100644
	--- a/CMakeLists.txt
	+++ b/CMakeLists.txt
	@@ -1984,6 +1984,7 @@ set(CPACK_PACKAGE_DESCRIPTION_FILE "${CMAKE_SOURCE_DIR}/README.md")
	 set(CPACK_PACKAGE_VENDOR "rr-debugger")

	 set(CPACK_DEBIAN_PACKAGE_MAINTAINER "rr-debugger")
	+set(CPACK_DEBIAN_PACKAGE_SHLIBDEPS ON)
	 set(CPACK_DEBIAN_PACKAGE_SECTION "devel")
	 if(${CMAKE_SYSTEM_PROCESSOR} STREQUAL "x86_64")
	   set(CPACK_DEBIAN_PACKAGE_ARCHITECTURE "amd64")
	EOF
      popd >/dev/null
      mkdir obj
      pushd obj >/dev/null
        CC=clang CXX=clang++ cmake -G Ninja -DCMAKE_BUILD_TYPE=Release -Dstrip=TRUE ../rr
        cmake --build .
        cpack -G DEB
        dpkg -i dist/rr-*.deb
      popd >/dev/null
    popd >/dev/null
    rm -rf "$TMPD"
    ;;
  test)
    rr --version
    ;;
esac
