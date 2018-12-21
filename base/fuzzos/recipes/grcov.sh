#!/usr/bin/env bash

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
