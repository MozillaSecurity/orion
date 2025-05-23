#!/bin/bash -ex
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=recipes/linux/common.sh
source ~worker/.local/bin/common.sh

sys-update
apt-install-auto pipx

PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin retry pipx install fxpoppet
su worker -c "fxpoppet-emulator --no-launch"
PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx uninstall fxpoppet

~worker/.local/bin/cleanup.sh

chown -R worker:worker /home/worker
