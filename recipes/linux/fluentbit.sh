#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Install fluentbit logging agent

apt-install-auto \
    ca-certificates \
    curl \
    gpg \
    gpg-agent \
    lsb-release

curl --retry 5 -sS "https://packages.fluentbit.io/fluentbit.key" | apt-key add -
cat > /etc/apt/sources.list.d/fluentbit.list << EOF
deb https://packages.fluentbit.io/ubuntu/$(lsb_release -sc) $(lsb_release -sc) main
EOF

sys-update
sys-embed \
    td-agent-bit
