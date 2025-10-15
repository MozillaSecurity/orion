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

#### Install Sentry CLI

case "${1-install}" in
  install)
    apt-install-auto \
      ca-certificates \
      curl

    if is-arm64; then
      PLATFORM="Linux-aarch64"
    elif is-amd64; then
      PLATFORM="Linux-x86_64"
    else
      echo "unknown platform" >&2
      exit 1
    fi

    LATEST_VERSION=$(get-latest-github-release "getsentry/sentry-cli")
    retry-curl -o /usr/local/bin/sentry-cli "https://github.com/getsentry/sentry-cli/releases/download/$LATEST_VERSION/sentry-cli-$PLATFORM"
    chmod +x /usr/local/bin/sentry-cli
    ;;
  test)
    sentry-cli --version
    ;;
esac
