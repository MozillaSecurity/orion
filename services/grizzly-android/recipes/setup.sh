#!/bin/bash -ex
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=base/linux/fuzzos/recipes/common.sh
source ~/.local/bin/common.sh

sys-update
sys-embed qemu-kvm

pip install -r /tmp/recipes/requirements.txt
python /tmp/recipes/emulator.py install avd

~/.local/bin/cleanup.sh

chown -R worker:worker /home/worker
usermod -a -G kvm worker
