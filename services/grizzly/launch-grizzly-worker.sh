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

SHIP="$(get-provider)"

function update_ec2_status {
  if [[ -n "$EC2SPOTMANAGER_POOLID" ]]; then
    python3 -m EC2Reporter --report "$@" || true
  elif [[ -n "$TASKCLUSTER_FUZZING_POOL" ]]; then
    python3 -m TaskStatusReporter --report "$@" || true
  fi
}

eval "$(ssh-agent -s)"
mkdir -p .ssh

# Get fuzzmanager configuration from credstash
retry credstash get fuzzmanagerconf > .fuzzmanagerconf

# Update fuzzmanager config for this instance
mkdir -p signatures
cat >> .fuzzmanagerconf << EOF
sigdir = $HOME/signatures
tool = bearspray
EOF
setup-fuzzmanager-hostname "$SHIP"
chmod 0600 .fuzzmanagerconf

# only clone if it wasn't already mounted via docker run -v
if [ ! -d ~/bearspray ]; then
  update_ec2_status "Setup: cloning bearspray"

  # Get deployment key from credstash
  retry credstash get deploy-bearspray.pem > .ssh/id_ecdsa.bearspray
  chmod 0600 .ssh/id_ecdsa.bearspray

  cat <<- EOF >> .ssh/config

	Host bearspray
	HostName github.com
	IdentitiesOnly yes
	IdentityFile ~/.ssh/id_ecdsa.bearspray
	EOF

  # Checkout bearspray
  git init bearspray
  ( cd bearspray
    git remote add -t master origin git@bearspray:MozillaSecurity/bearspray.git
    retry git fetch -v --depth 1 --no-tags origin master
    git reset --hard FETCH_HEAD
  )
fi

update_ec2_status "Setup: installing bearspray"
pip3 install --user -U -e ./bearspray

update_ec2_status "Setup: launching bearspray"

screen -dmLS grizzly /bin/bash
sleep 5
screen -S grizzly -X screen rwait run "$wait_token" python3 -m bearspray --screen --xvfb
