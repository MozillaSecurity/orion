#!/bin/bash -ex

apt-get update -y -qq

apt-get install -q -y --no-install-recommends adb

apt-get clean -y
apt-get autoclean -y
apt-get autoremove -y

rm -rf /var/lib/apt/lists/*
rm -rf /root/.cache/*

python /tmp/recipes/emulator.py

chown -R worker:worker /home/worker
