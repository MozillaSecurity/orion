#!/bin/bash -ex

# shellcheck disable=SC1091
source ./recipes/common.sh

#### rg (ripgrep)

LATEST_VERSION=$(curl -Ls 'https://api.github.com/repos/BurntSushi/ripgrep/releases/latest' | grep -Po '"tag_name": "\K.*?(?=")')
retry curl -LO "https://github.com/BurntSushi/ripgrep/releases/download/${LATEST_VERSION}/ripgrep_${LATEST_VERSION}_amd64.deb"
apt install ./"ripgrep_${LATEST_VERSION}_amd64.deb"
rm "ripgrep_${LATEST_VERSION}_amd64.deb"
