#!/bin/bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# Install taskcluster CLI
cd "${0%/*}"
./taskcluster.sh

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"
/home/worker/.local/bin/cleanup.sh

# Cleanup grizzly scripts
rm /home/worker/launch-grizzly*

# Create logfile
touch /live.log

#### Fix ownership
chown -R worker:worker /live.log
chown -R worker:worker /home/worker
