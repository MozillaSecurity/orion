#!/bin/bash -ex

function retry {
  # shellcheck disable=SC2015
  for _ in {1..9}; do
    "$@" && return || sleep 30
  done
  "$@"
}

eval "$(ssh-agent -s)"
mkdir -p .ssh
retry ssh-keyscan github.com >> .ssh/known_hosts

# Get deployment keys from credstash
retry credstash get deploy-grizzly-config.pem > .ssh/id_ecdsa.grizzly_config
chmod 0600 .ssh/id_ecdsa.grizzly_config

# Setup Additional Key Identities
cat << EOF >> .ssh/config

Host grizzly-config
HostName github.com
IdentitiesOnly yes
IdentityFile ~/.ssh/id_ecdsa.grizzly_config
EOF

# Checkout fuzzer including framework, install everything
retry git clone -v --depth 1 --no-tags git@grizzly-config:MozillaSecurity/grizzly-config.git config
./config/aws/setup-grizzly.sh

# need to keep the container running
while true
do
    sleep 300
done
