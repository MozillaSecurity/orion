#!/bin/bash -ex

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

if [ ! -e /dev/kvm ]
then
    mknod /dev/kvm c 10 "$(grep '\<kvm\>' /proc/misc | cut -f 1 -d' ')"
fi
usermod -a -G kvm worker
chgrp kvm /dev/kvm
chmod 0660 /dev/kvm
