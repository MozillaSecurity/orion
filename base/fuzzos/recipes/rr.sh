#!/bin/bash -ex

#### Install rr

source base/fuzzos/recipes/common.sh

apt-install-auto \
  ccache \
  cmake \
  make \
  g++-multilib gdb \
  pkg-config \
  coreutils \
  python-pexpect \
  manpages-dev git \
  ninja-build \
  capnproto \
  libcapnp-dev

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
