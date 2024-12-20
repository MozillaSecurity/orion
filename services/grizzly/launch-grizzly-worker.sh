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

pushd /src/fuzzmanager >/dev/null
  retry git fetch -q --depth 1 --no-tags origin master
  git reset --hard origin/master
popd >/dev/null

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

# Get Cloud Storage credentials
if [[ "$ADAPTER" != "reducer" ]]; then
  mkdir -p ~/.config/gcloud
  if [[ "$ADAPTER" = "crashxp" ]]; then
    get-tc-secret ci-gcs-crashxp-data ~/.config/gcloud/application_default_credentials.json raw
  else
    get-tc-secret google-cloud-storage-creds ~/.config/gcloud/application_default_credentials.json raw
  fi
fi

# only clone if it wasn't already mounted via docker run -v
if [ ! -d /src/bearspray ]; then
  update-status "Setup: cloning bearspray"

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

update-status "Setup: installing bearspray"
retry python3 -m pip install --user --no-build-isolation -e /src/bearspray

update-status "Setup: launching bearspray"

export GCOV=/usr/local/bin/gcov-9

screen -dmLS grizzly /bin/bash
sleep 5
# shellcheck disable=SC2086
screen -S grizzly -X screen rwait run "$wait_token" python3 -m bearspray "$ADAPTER" --screen --headless $HEADLESS
