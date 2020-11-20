#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"
source /etc/lsb-release

#### Install ripgrep

if [ "$DISTRIB_RELEASE" = "18.04" ]; then
  apt-install-auto \
    ca-certificates \
    curl

  VERSION="12.1.1"

  DOWNLOAD_URL="https://github.com/BurntSushi/ripgrep/releases/download/${VERSION}/ripgrep_${VERSION}_amd64.deb"

  TMPD="$(mktemp -d -p. rg.build.XXXXXXXXXX)"
  ( cd "$TMPD"
    curl --retry 5 -sLO "$DOWNLOAD_URL"
    dpkg -i ./ripgrep_${VERSION}_*.deb
  )
  rm -rf "$TMPD"
else
  sys-embed ripgrep
fi
