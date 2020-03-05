#!/bin/bash -ex
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=recipes/linux/common.sh
source ~/.local/bin/common.sh

sys-update
sys-embed qemu-kvm

pip3 install -r /tmp/recipes/requirements.txt
python3 /tmp/recipes/emulator.py install avd

~/.local/bin/cleanup.sh

chown -R worker:worker /home/worker
usermod -a -G kvm worker
