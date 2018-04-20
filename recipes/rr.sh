#!/bin/bash -ex

# calls `apt-get install` on it's arguments but marks them as automatically installed
# previously installed packages are not affected
apt-install-auto () {
  new=()
  for pkg in "$@"; do
    if ! dpkg -l "$pkg" 2>&1 | grep -q ^ii; then
      new+=("$pkg")
    fi
  done
  apt-get -y -qq --no-install-recommends --no-install-suggests install "${new[@]}"
  apt-mark auto "${new[@]}"
}

apt-install-auto ccache cmake make g++-multilib gdb \
  pkg-config coreutils python-pexpect manpages-dev git \
  ninja-build capnproto libcapnp-dev

TMPD="$(mktemp -d -p. rr.build.XXXXXXXXXX)"
( cd "$TMPD"
  git clone https://github.com/mozilla/rr.git
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

# Instructions for installing latest release-version:
#PLATFORM=$(uname -m)
#LATEST_VERSION="$(curl -Ls 'https://api.github.com/repos/mozilla/rr/releases/latest' | python -c "import sys,json; sys.stdout.write(json.load(sys.stdin)['tag_name'])")"
#curl -L -o /tmp/rr.deb "https://github.com/mozilla/rr/releases/download/$LATEST_VERSION/rr-$LATEST_VERSION-Linux-$PLATFORM.deb"
#dpkg -i /tmp/rr.deb
#rm /tmp/rr.deb
