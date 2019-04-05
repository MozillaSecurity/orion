#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=base/fuzzos/recipes/common.sh
source "${0%/*}/common.sh"

#### Install grcov

PLATFORM="linux-x86_64"
LATEST_VERSION=$(get-latest-github-release "mozilla/grcov")
retry curl -LO "https://github.com/mozilla/grcov/releases/download/$LATEST_VERSION/grcov-$PLATFORM.tar.bz2"
tar xf grcov-$PLATFORM.tar.bz2
install grcov /usr/local/bin/grcov
rm grcov grcov-$PLATFORM.tar.bz2
