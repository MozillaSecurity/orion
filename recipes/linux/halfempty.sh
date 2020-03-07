#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Install halfempty

sys-embed \
    libglib2.0-0
apt-install-auto \
    bsdmainutils \
    ca-certificates \
    curl \
    gcc \
    libglib2.0-dev \
    make \
    pkg-config

NAME="halfempty"
VERSION="0.30"
DOWNLOAD_URL="https://github.com/googleprojectzero/halfempty/archive/v$VERSION.tar.gz"

TMPD="$(mktemp -d -p. halfempty.build.XXXXXXXXXX)"
( cd "$TMPD"
  curl --retry 5 -sL "$DOWNLOAD_URL" | tar -xzv
  cd "$NAME-$VERSION"
  make
  mv "$NAME" /usr/local/bin/
)
rm -rf "$TMPD"
