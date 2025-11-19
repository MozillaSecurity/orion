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
      binutils
      ca-certificates
      curl
      lbzip2
    )

    apt-install-auto "${pkgs[@]}"

    TMPD="$(mktemp -d -p. grcov.XXXXXXXXXX)"
    pushd "$TMPD" >/dev/null

    LATEST_VERSION=$(get-latest-github-release "mozilla/grcov")
    if is-arm64; then
      asset="grcov-aarch64-unknown-linux-gnu.tar.bz2"
    else
      asset="grcov-x86_64-unknown-linux-gnu.tar.bz2"
    fi

    retry-curl -O "https://github.com/mozilla/grcov/releases/download/$LATEST_VERSION/$asset"
    tar -I lbzip2 -xf "$asset"
    install grcov /usr/local/bin/grcov
    strip --strip-unneeded /usr/local/bin/grcov

    popd >/dev/null
    rm -rf "$TMPD"
    ;;
  test)
    grcov --help
    grcov --version
    ;;
esac
