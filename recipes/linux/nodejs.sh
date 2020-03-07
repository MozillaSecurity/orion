#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Install NodeJS

apt-install-auto \
    binutils \
    ca-certificates \
    curl

curl --retry 5 -sL https://deb.nodesource.com/setup_10.x | bash -
sys-embed nodejs
strip --strip-unneeded /usr/bin/node
