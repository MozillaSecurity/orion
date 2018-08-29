#!/bin/bash -ex

apt-get update -y -qq

apt-get install -q -y --no-install-recommends adb

apt-get clean -y
apt-get autoclean -y
apt-get autoremove -y

rm -rf /var/lib/apt/lists/*
rm -rf /root/.cache/*

# Create the kvm node
mknod /dev/kvm c 10 "$(grep '\<kvm\>' /proc/misc | cut -f 1 -d' ')"
chmod 0666 /dev/kvm

python /tmp/recipes/emulator.py

chown -R worker:worker /home/worker
