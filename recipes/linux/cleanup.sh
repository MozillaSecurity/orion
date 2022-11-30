#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

#### Cleanup Artifacts

rm -rf /usr/share/man/ || echo "'rm -rf /usr/share/man' failed"
rm -rf /usr/share/info/ || echo "'rm -rf /usr/share/info' failed"
find /usr/share/doc -depth -type f ! -name copyright -exec rm {} +
find /usr/share/doc -empty -exec rmdir {} +
apt-get clean -y
apt-get autoremove --purge -y
rm -rf /var/lib/apt/lists/* || echo "'rm -rf /var/lib/apt/lists/*' failed"
rm -rf /var/log/* || echo "'rm -rf /var/log/*' failed"
rm -rf /root/.cache/* || echo "'rm -rf /root/.cache/*' failed"
rm -rf /tmp/* || echo "'rm -rf /tmp/*' failed"
