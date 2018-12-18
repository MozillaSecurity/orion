#!/bin/bash -ex

# shellcheck disable=SC1091
source ./recipes/common.sh

#### Install rg (ripgrep)

STABLE_VERSION="0.10.0"
curl -LO "https://github.com/BurntSushi/ripgrep/releases/download/${STABLE_VERSION}/ripgrep_${STABLE_VERSION}_amd64.deb"
apt install "./ripgrep_${STABLE_VERSION}_amd64.deb"
rm "ripgrep_${STABLE_VERSION}_amd64.deb"
