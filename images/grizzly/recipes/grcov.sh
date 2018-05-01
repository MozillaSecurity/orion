#!/bin/bash -ex

cd "$HOME"
git clone -v --depth 1 https://github.com/marco-c/grcov.git

(cd grcov

# from install.sh

PLATFORM=linux-x86_64
LATEST_VERSION="$(curl -Ls 'https://api.github.com/repos/marco-c/grcov/releases/latest' | python -c "import sys, json; print json.load(sys.stdin)['tag_name']")"

rm -f grcov "grcov-$PLATFORM.tar.bz2"
curl -LO "https://github.com/marco-c/grcov/releases/download/$LATEST_VERSION/grcov-$PLATFORM.tar.bz2"
tar xf "grcov-$PLATFORM.tar.bz2"
install grcov /usr/local/bin/grcov
)
rm -rf grcov
