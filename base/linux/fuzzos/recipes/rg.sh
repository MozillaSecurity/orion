#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=base/linux/fuzzos/recipes/common.sh
source "${0%/*}/common.sh"

#### Install ripgrep

VERSION="0.10.0-2"

if is-amd64; then
  DOWNLOAD_URL="https://launchpad.net/ubuntu/+source/rust-ripgrep/${VERSION}/+build/16383499/+files/ripgrep_${VERSION}_amd64.deb"
fi

if is-arm64; then
  DOWNLOAD_URL="https://launchpad.net/ubuntu/+source/rust-ripgrep/${VERSION}/+build/16383500/+files/ripgrep_${VERSION}_arm64.deb"
fi

TMPD="$(mktemp -d -p. rg.build.XXXXXXXXXX)"
( cd "$TMPD"
  retry curl -LO "$DOWNLOAD_URL"
  apt install ./ripgrep_${VERSION}_*.deb
)
rm -rf "$TMPD"
