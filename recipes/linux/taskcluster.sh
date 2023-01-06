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

#### Install Taskcluster CLI

case "${1-install}" in
  install)
    apt-install-auto \
        ca-certificates \
        curl

    if is-arm64; then
      PLATFORM="linux-arm64"
    elif is-amd64; then
      PLATFORM="linux-amd64"
    else
      echo "unknown platform" >&2
      exit 1
    fi

    TMPD="$(mktemp -d -p. tc.XXXXXXXXXX)"
    pushd "$TMPD" >/dev/null
      LATEST_VERSION=$(get-latest-github-release "taskcluster/taskcluster")
      curl --retry 5 -sLO "https://github.com/taskcluster/taskcluster/releases/download/$LATEST_VERSION/taskcluster-$PLATFORM.tar.gz"
      tar -xzf taskcluster-$PLATFORM.tar.gz
      install taskcluster /usr/local/bin/taskcluster
    popd >/dev/null
    rm -rf "$TMPD"
    ;;
  test)
    taskcluster version
    ;;
esac
