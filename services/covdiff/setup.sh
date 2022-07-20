#!/bin/bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

mkdir -p /home/worker/.local/bin

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

cp "${0%/*}/common.sh" /home/worker/.local/bin/common.sh
printf "source ~/.local/bin/common.sh\n" >> /home/worker/.bashrc

#### Bootstrap Packages

sys-update

#### Install recipes

cd "${0%/*}"
./taskcluster.sh
./fuzzmanager.sh

# Create logfile
touch /live.log

#### Fix ownership
chown -R worker:worker /live.log
chown -R worker:worker /home/worker
chmod 0777 /src
