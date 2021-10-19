#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

wait_token="$1"
shift

# shellcheck source=recipes/linux/common.sh
source ~/.local/bin/common.sh

eval "$(ssh-agent -s)"
mkdir -p .ssh

# Get fuzzmanager configuration from TC
get-tc-secret fuzzmanagerconf .fuzzmanagerconf

# Update fuzzmanager config for this instance
mkdir -p signatures
cat >> .fuzzmanagerconf << EOF
sigdir = $HOME/signatures
tool = bearspray
EOF
setup-fuzzmanager-hostname
chmod 0600 .fuzzmanagerconf

# only clone if it wasn't already mounted via docker run -v
if [ ! -d /src/bearspray ]; then
  update-ec2-status "Setup: cloning bearspray"

  # Get deployment key from TC
  get-tc-secret deploy-bearspray .ssh/id_ecdsa.bearspray

  cat <<- EOF >> .ssh/config

	Host bearspray
	HostName github.com
	IdentitiesOnly yes
	IdentityFile ~/.ssh/id_ecdsa.bearspray
	EOF

  # Checkout bearspray
  git-clone git@bearspray:MozillaSecurity/bearspray.git /src/bearspray
fi

update-ec2-status "Setup: installing bearspray"
retry python3 -m pip install --user -U -e /src/bearspray

update-ec2-status "Setup: launching bearspray"

export GCOV=/usr/local/bin/gcov-9

screen -dmLS grizzly /bin/bash
sleep 5
screen -S grizzly -X screen rwait run "$wait_token" python3 -m bearspray "$ADAPTER" --screen --xvfb
