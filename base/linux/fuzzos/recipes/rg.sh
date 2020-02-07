#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=base/linux/fuzzos/recipes/common.sh
source "${0%/*}/common.sh"

#### Install rg (ripgrep)

VERSION="0.10.0"
DOWNLOAD_URL="https://github.com/BurntSushi/ripgrep/releases/download/${VERSION}/ripgrep_${VERSION}_amd64.deb"

curl -LO "$DOWNLOAD_URL"
dpkg -i "./ripgrep_${VERSION}_amd64.deb"
rm "ripgrep_${VERSION}_amd64.deb"
