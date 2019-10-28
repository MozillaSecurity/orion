#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=base/linux/fuzzos/recipes/common.sh
source "${0%/*}/common.sh"

#### Install halfempty

apt-install-auto \
    bsdmainutils \
    pkg-config \
    gcc \
    libglib2.0-dev

NAME="halfempty"
VERSION="0.30"
DOWNLOAD_URL="https://github.com/googleprojectzero/halfempty/archive/v$VERSION.tar.gz"

TMPD="$(mktemp -d -p. halfempty.build.XXXXXXXXXX)"
( cd "$TMPD"
  retry curl -L "$DOWNLOAD_URL" | tar -xzv
  cd "$NAME-$VERSION"
  make
  mv "$NAME" /usr/local/bin/
)
rm -rf "$TMPD"
