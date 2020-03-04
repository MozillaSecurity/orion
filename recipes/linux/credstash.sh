#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Install credstash

apt-install-auto gcc libssl-dev
sys-embed libssl1.1

pip3 install credstash
