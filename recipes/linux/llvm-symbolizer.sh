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

#### Install LLVM

VERSION=12

case "${1-install}" in
  install)
    apt-install-auto \
      binutils \
      ca-certificates \
      curl \
      zstd

    retry-curl "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.cache.level-3.toolchains.v3.linux64-clang-${VERSION}.latest/artifacts/public/build/clang.tar.zst" | zstdcat | tar -x -C /usr/local/bin --strip-components=2 clang/bin/llvm-symbolizer
    strip --strip-unneeded /usr/local/bin/llvm-symbolizer
    ;;
  test)
    llvm-symbolizer --version
    ;;
esac
