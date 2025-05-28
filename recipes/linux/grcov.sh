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

#### Install grcov

case "${1-install}" in
  install)
    pkgs=(
      ca-certificates
      curl
    )
    if is-arm64; then
      pkgs+=(lbzip2)
    else
      pkgs+=(
        binutils
        zstd
      )
    fi
    apt-install-auto "${pkgs[@]}"

    if is-arm64; then
      TMPD="$(mktemp -d -p. grcov.XXXXXXXXXX)"
      pushd "$TMPD" >/dev/null
      LATEST_VERSION=$(get-latest-github-release "mozilla/grcov")
      retry-curl -O "https://github.com/mozilla/grcov/releases/download/$LATEST_VERSION/grcov-aarch64-unknown-linux-gnu.tar.bz2"
      tar -I lbzip2 -xf grcov-aarch64-unknown-linux-gnu.tar.bz2
      install grcov /usr/local/bin/grcov
      popd >/dev/null
      rm -rf "$TMPD"
    else
      retry-curl "$(resolve-tc grcov)" | zstdcat | tar -x -v --strip-components=1 -C /usr/local/bin
      strip --strip-unneeded /usr/local/bin/grcov
    fi
    ;;
  test)
    grcov --help
    grcov --version
    ;;
esac
