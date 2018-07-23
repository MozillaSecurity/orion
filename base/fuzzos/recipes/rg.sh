#!/bin/bash -ex

source base/fuzzos/recipes/common.sh

#### rg (ripgrep)

LATEST_VERSION=$(curl -Ls 'https://api.github.com/repos/BurntSushi/ripgrep/releases/latest' | grep -Po '"tag_name": "\K.*?(?=")')
retry curl -LO "https://github.com/BurntSushi/ripgrep/releases/download/${LATEST_VERSION}/ripgrep_${LATEST_VERSION}_amd64.deb"
apt install ./ripgrep_0.8.1_amd64.deb
rm "ripgrep_${LATEST_VERSION}_amd64.deb"
