#!/bin/bash -ex

# shellcheck disable=SC1091
source ./recipes/common.sh

#### Install rg (ripgrep)

LATEST_VERSION=$(curl -s "https://github.com/BurntSushi/ripgrep/releases/latest" | grep -o 'tag/[v.0-9]*' | awk -F/ '{print $2}')
retry curl -LO "https://github.com/BurntSushi/ripgrep/releases/download/${LATEST_VERSION}/ripgrep_${LATEST_VERSION}_amd64.deb"
apt install ./"ripgrep_${LATEST_VERSION}_amd64.deb"
rm "ripgrep_${LATEST_VERSION}_amd64.deb"
