#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Install grcov

apt-install-auto curl ca-certificates

ARM64_RUST_VERSION="1.37.0"

TMPD="$(mktemp -d -p. grcov.XXXXXXXXXX)"
( cd "$TMPD"
  if is-arm64; then
    # Todo: outsource and pull the binary in as a multi-stage build step.
    curl --retry 5 -sLO "https://static.rust-lang.org/dist/rust-${ARM64_RUST_VERSION}-aarch64-unknown-linux-gnu.tar.gz"
    tar xzf rust-${ARM64_RUST_VERSION}-aarch64-unknown-linux-gnu.tar.gz
    cd rust-${ARM64_RUST_VERSION}-aarch64-unknown-linux-gnu

    ./install.sh
    retry cargo install --force grcov --root /usr/local
    rm -rf ~/.cargo
    /usr/local/lib/rustlib/uninstall.sh
  fi

  if is-amd64; then
    PLATFORM="linux-x86_64"
    LATEST_VERSION=$(get-latest-github-release "mozilla/grcov")
    curl --retry 5 -sLO "https://github.com/mozilla/grcov/releases/download/$LATEST_VERSION/grcov-$PLATFORM.tar.bz2"
    tar xf grcov-$PLATFORM.tar.bz2
    install grcov /usr/local/bin/grcov
    rm grcov grcov-$PLATFORM.tar.bz2
  fi
)
rm -rf "$TMPD"
