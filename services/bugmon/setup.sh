#!/bin/bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

export PATH=$PATH:/home/worker/.local/bin

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

# Install 32-bit binaries
dpkg --add-architecture i386
sys-update
sys-embed libc6-dbg:i386 libatomic1:i386 libstdc++6:i386 libnspr4:i386
cleanup.sh

# Cleanup grizzly scripts
rm /home/worker/launch-grizzly*

#### Create aritfact directory
mkdir /bugmon-artifacts

#### Fix ownership
chown -R worker:worker /bugmon-artifacts
chown -R worker:worker /home/worker
