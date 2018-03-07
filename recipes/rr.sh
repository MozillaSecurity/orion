#!/bin/bash -ex
PLATFORM=$(uname -m)
LATEST_VERSION="$(curl -Ls 'https://api.github.com/repos/mozilla/rr/releases/latest' | python -c "import sys,json; sys.stdout.write(json.load(sys.stdin)['tag_name'])")"

curl -L -o /tmp/rr.deb https://github.com/mozilla/rr/releases/download/$LATEST_VERSION/rr-$LATEST_VERSION-Linux-$PLATFORM.deb
dpkg -i /tmp/rr.deb
rm /tmp/rr.deb
