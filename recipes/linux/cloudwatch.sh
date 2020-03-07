#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

apt-install-auto \
    ca-certificates \
    curl

TMPD="$(mktemp -d -p. cloudwatch.XXXXXXXXXX)"
( cd "$TMPD"
  curl --connect-timeout 10 --retry 5 -LO https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
  dpkg -i amazon-cloudwatch-agent.deb
)
rm -rf "$TMPD"
