#!/bin/bash -ex

. ./recipes/common.sh

#### grcov

PLATFORM="linux-x86_64"
LATEST_VERSION=$(curl -Ls 'https://api.github.com/repos/marco-c/grcov/releases/latest' | grep -Po '"tag_name": "\K.*?(?=")')
retry curl -LO "https://github.com/marco-c/grcov/releases/download/$LATEST_VERSION/grcov-$PLATFORM.tar.bz2"
tar xf grcov-$PLATFORM.tar.bz2
install grcov /usr/local/bin/grcov
rm grcov grcov-$PLATFORM.tar.bz2
