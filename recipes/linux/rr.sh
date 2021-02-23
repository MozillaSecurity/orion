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

#### Install rr

if is-arm64; then
  echo "[INFO] rr is currently not supported on any ARM architecture."
  exit
fi

case "${1-install}" in
  install)
    apt-install-auto \
      ca-certificates \
      curl

    TMPD="$(mktemp -d -p. rr.dl.XXXXXXXXXX)"
    pushd "$TMPD" >/dev/null
      PLATFORM="Linux-x86_64"
      LATEST_VERSION=$(get-latest-github-release "rr-debugger/rr")
      FN="rr-$LATEST_VERSION-$PLATFORM.deb"
      curl --retry 5 -sLO "https://github.com/rr-debugger/rr/releases/download/$LATEST_VERSION/$FN"
      sys-embed "./$FN"
    popd >/dev/null
    rm -rf "$TMPD"
    ;;
  test)
    rr help
    ;;
esac
