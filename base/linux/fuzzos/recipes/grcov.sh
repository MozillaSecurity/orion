#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=base/fuzzos/recipes/common.sh
source "${0%/*}/common.sh"

#### Install grcov

ARM64_RUST_VERSION="1.37.0"

if is-arm64; then
  TMPD="$(mktemp -d -p. grcov.XXXXXXXXXX)"
  ( cd "$TMPD"
    # Todo: outsource and pull the binary in as a multi-stage build step.
    retry curl -LO "https://static.rust-lang.org/dist/rust-${ARM64_RUST_VERSION}-aarch64-unknown-linux-gnu.tar.gz"
    tar xzf rust-${ARM64_RUST_VERSION}-aarch64-unknown-linux-gnu.tar.gz
    cd rust-${ARM64_RUST_VERSION}-aarch64-unknown-linux-gnu

    ./install.sh
    retry cargo install --force grcov
    mv "$HOME/.cargo/bin/grcov" /usr/local/bin/
    rm -rf "$HOME/.cargo/registry"
    /usr/local/lib/rustlib/uninstall.sh
  )
  rm -rf "$TMPD"
fi

if is-amd64; then
  PLATFORM="linux-x86_64"
  LATEST_VERSION=$(get-latest-github-release "mozilla/grcov")
  retry curl -LO "https://github.com/mozilla/grcov/releases/download/$LATEST_VERSION/grcov-$PLATFORM.tar.bz2"
  tar xf grcov-$PLATFORM.tar.bz2
  install grcov /usr/local/bin/grcov
  rm grcov grcov-$PLATFORM.tar.bz2
fi
