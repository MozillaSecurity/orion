#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

#### Cleanup Artifacts

rm -rf /usr/share/man/ /usr/share/info/
find /usr/share/doc -depth -type f ! -name copyright -exec rm {} +
find /usr/share/doc -empty -exec rmdir {} +
apt-get clean -y
apt-get autoremove --purge -y
rm -rf /var/lib/apt/lists/*
rm -rf /var/log/*
rm -rf /root/.cache/*
rm -rf /tmp/*
