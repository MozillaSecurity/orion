#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=base/fuzzos/recipes/common.sh
source "${0%/*}/common.sh"

#### Install rg (ripgrep)

STABLE_VERSION="0.10.0"
curl -LO "https://github.com/BurntSushi/ripgrep/releases/download/${STABLE_VERSION}/ripgrep_${STABLE_VERSION}_amd64.deb"
apt install "./ripgrep_${STABLE_VERSION}_amd64.deb"
rm "ripgrep_${STABLE_VERSION}_amd64.deb"
