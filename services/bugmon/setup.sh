#!/bin/bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

# Install 32-bit binaries
cd "${0%/*}"
./js32_deps.sh
./pernosco_submit.sh
sys-embed libc6-dbg:i386
./cleanup.sh

# Cleanup grizzly scripts
rm /home/worker/launch-grizzly*

#### Create aritfact directory
mkdir /bugmon-artifacts

#### Fix ownership
chown -R worker:worker /bugmon-artifacts
chown -R worker:worker /home/worker
