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

# Get AWS credentials for GCE to be able to read from Credstash
if [[ "$EC2SPOTMANAGER_PROVIDER" = "GCE" ]]; then
  mkdir -p .aws
  retry berglas access fuzzmanager-cluster-secrets/credstash-aws-auth > .aws/credentials
  chmod 0600 .aws/credentials
elif [[ -n "$TASKCLUSTER_PROXY_URL" ]]; then
  mkdir -p .aws
  curl -L "$TASKCLUSTER_PROXY_URL/secrets/v1/secret/project/fuzzing/credstash-aws-auth" | jshon -e secret -e key -u > .aws/credentials
  chmod 0600 .aws/credentials
fi

if [ -d ~/.config ]; then
  # Get deployment keys from credstash
  retry credstash get deploy-grizzly-config.pem > .ssh/id_ecdsa.grizzly_config
  chmod 0600 .ssh/id_ecdsa.grizzly_config

  # Setup Additional Key Identities
  cat <<- EOF >> .ssh/config

	Host grizzly-config
	HostName github.com
	IdentitiesOnly yes
	IdentityFile ~/.ssh/id_ecdsa.grizzly_config
	EOF

  # Checkout fuzzer including framework, install everything
  retry git clone -v --depth 1 --no-tags git@grizzly-config:MozillaSecurity/grizzly-config.git config
fi

./config/aws/setup-bearspray.sh "$wait_token"
