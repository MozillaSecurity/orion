#!/bin/bash -ex
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

apt-get update -y -qq
apt-get install -q -y --no-install-recommends \
    qemu-kvm
apt-get clean -y
apt-get autoclean -y
apt-get autoremove -y
rm -rf /var/lib/apt/lists/*

pip install -r /tmp/recipes/requirements.txt
python /tmp/recipes/emulator.py install avd

chown -R worker:worker /home/worker
usermod -a -G kvm worker
