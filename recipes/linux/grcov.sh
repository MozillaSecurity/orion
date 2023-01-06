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

#### Install grcov

case "${1-install}" in
  install)
    apt-install-auto \
      ca-certificates \
      curl

    if is-arm64; then
      PLATFORM="aarch64-unknown-linux-gnu"
    elif is-amd64; then
      PLATFORM="x86_64-unknown-linux-gnu"
    else
      echo "unknown platform" >&2
      exit 1
    fi

    TMPD="$(mktemp -d -p. grcov.XXXXXXXXXX)"
    pushd "$TMPD" >/dev/null
      LATEST_VERSION=$(get-latest-github-release "mozilla/grcov")
      retry-curl -O "https://github.com/mozilla/grcov/releases/download/$LATEST_VERSION/grcov-$PLATFORM.tar.bz2"
      tar xf grcov-$PLATFORM.tar.bz2
      install grcov /usr/local/bin/grcov
      rm grcov grcov-$PLATFORM.tar.bz2
    popd >/dev/null
    rm -rf "$TMPD"
    ;;
  test)
    grcov --help
    grcov --version
    ;;
esac
