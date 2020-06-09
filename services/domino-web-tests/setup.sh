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

cd "${0%/*}"
./taskcluster.sh

#### Install packages

packages=(
  libdbus-glib-1-2
  libgtk-3-0
  libx11-xcb1
  libxt6
)
sys-embed "${packages[@]}"

#### Clean up

./cleanup.sh

#### Fix ownership

chmod 0600 /home/worker/.ssh/config
chown -R worker:worker /home/worker
