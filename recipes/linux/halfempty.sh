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

#### Install halfempty

VERSION="0.30"
DOWNLOAD_URL="https://github.com/googleprojectzero/halfempty/archive/v$VERSION.tar.gz"

case "${1-install}" in
  install)
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

    TMPD="$(mktemp -d -p. halfempty.build.XXXXXXXXXX)"
    pushd "$TMPD" >/dev/null
    retry-curl "$DOWNLOAD_URL" | tar -xzv
    cd "halfempty-$VERSION"
    make
    mv halfempty /usr/local/bin/
    popd >/dev/null
    rm -rf "$TMPD"
    ;;
  test)
    halfempty --help-all
    ;;
esac
