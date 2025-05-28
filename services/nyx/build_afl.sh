#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

export DEBIAN_FRONTEND="noninteractive"

pkgs=(
  bzip2
  cpio
  gcc
  git
  libblocksruntime-dev
  libcurl4-openssl-dev
  libgtk-3-dev
  libjson-c-dev
  libssl-dev
  make
  patch
  pax-utils
  python3-jinja2
  python3-msgpack
  zstd
)

sys-update
sys-embed "${pkgs[@]}"

# shellcheck source=services/nyx/clang.sh
source "${0%/*}/clang.sh"
retry-curl "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.cache.level-3.toolchains.v3.sysroot-x86_64-linux-gnu.latest/artifacts/public/build/sysroot-x86_64-linux-gnu.tar.zst" | zstdcat | tar -x -C /opt

function git-clone-rev() {
  local dest rev url
  url="$1"
  rev="$2"
  if [[ $# -eq 3 ]]; then
    dest="$3"
  else
    dest="$(basename "$1" .git)"
  fi
  git init "$dest"
  pushd "$dest" >/dev/null || return 1
  git remote add origin "$url"
  retry git fetch -q --depth 1 --no-tags origin "$rev"
  git -c advice.detachedHead=false checkout "$rev"
  popd >/dev/null || return 1
}

# build AFL++ w/ Nyx
mkdir -p /srv/repos
pushd /srv/repos >/dev/null
git-clone-rev https://github.com/AFLplusplus/AFLplusplus 78b7e14c73baacf1d88b3c03955e78f5080d17ba
pushd AFLplusplus >/dev/null

# WIP 2-byte chunked variant of honggfuzz custom mutator
git apply /srv/repos/setup/patches/hongfuzz-2b-chunked.diff
git apply /srv/repos/setup/patches/increase-map-size.diff
make -f GNUmakefile afl-fuzz afl-showmap CODE_COVERAGE=1
pushd custom_mutators/honggfuzz >/dev/null
make
popd >/dev/null

# web services custom mutator
pushd custom_mutators >/dev/null
for mutator in /srv/repos/setup/custom_mutators/*; do
  dir_name=$(basename "$mutator")
  cp -r "$mutator" ./
  pushd "$dir_name" >/dev/null
  make
  popd >/dev/null
done
popd >/dev/null

pushd nyx_mode >/dev/null
git submodule init

retry git submodule update --depth 1 --single-branch libnyx
pushd libnyx >/dev/null
git apply /srv/repos/setup/patches/libnyx.diff
popd >/dev/null

retry git submodule update --depth 1 --single-branch packer
retry git submodule update --depth 1 --single-branch QEMU-Nyx
pushd QEMU-Nyx >/dev/null
git submodule init
retry git submodule update --depth 1 --single-branch capstone_v4
retry git submodule update --depth 1 --single-branch libxdc
export CAPSTONE_ROOT="$PWD/capstone_v4"
export LIBXDC_ROOT="$PWD/libxdc"
sed -i '/^LDFLAGS =$/d' libxdc/Makefile
git apply /srv/repos/setup/patches/nyx.diff
popd >/dev/null

NO_CHECKOUT=1 ./build_nyx_support.sh
popd >/dev/null
find . -name .git -type d -exec rm -rf '{}' +
find . -name \*.o -delete
find . -executable -type f -execdir strip '{}' + -o -true || true
popd >/dev/null
popd >/dev/null
