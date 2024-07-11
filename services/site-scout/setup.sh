#!/bin/bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Bootstrap Packages

sys-update

#### Install recipes
/src/recipes/grcov.sh

sys-embed ripgrep

# Cleanup grizzly scripts
rm /home/worker/launch-grizzly*

#### Fix ownership
chown -R worker:worker /home/worker

"${0%/*}/cleanup.sh"
