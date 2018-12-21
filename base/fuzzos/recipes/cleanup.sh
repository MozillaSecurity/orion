#!/usr/bin/env bash

set -x

#### Cleanup Artifacts

rm -rf /usr/share/man/ /usr/share/info/
find /usr/share/doc -depth -type f ! -name copyright -exec rm {} +
find /usr/share/doc -empty -exec rmdir {} +
apt-get clean -y
apt-get autoclean -y
apt-get autoremove -y
rm -rf /var/lib/apt/lists/*
rm -rf /root/.cache/*
rm -rf /tmp/*
