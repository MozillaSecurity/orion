#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Install remote_syslog

VERSION="0.20"
DOWNLOAD_URL="https://github.com/papertrail/remote_syslog2/releases/download/v${VERSION}/remote-syslog2_${VERSION}_amd64.deb"

curl -LO "$DOWNLOAD_URL"
dpkg -i "./remote-syslog2_${VERSION}_amd64.deb"
rm "remote-syslog2_${VERSION}_amd64.deb"
