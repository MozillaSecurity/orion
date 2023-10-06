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
# shellcheck source=recipes/linux/taskgraph-m-c-latest.sh
source "${0%/*}/taskgraph-m-c-latest.sh"

#### Install LLVM Symbolizer

case "${1-install}" in
  install)
    apt-install-auto \
      binutils \
      ca-certificates \
      curl \
      zstd

    retry-curl "$(resolve-tc llvm-symbolizer)" | zstdcat | tar -x -v --strip-components=2 -C /usr/local/bin
    strip --strip-unneeded /usr/local/bin/llvm-symbolizer
    ;;
  test)
    llvm-symbolizer --version
    ;;
esac
