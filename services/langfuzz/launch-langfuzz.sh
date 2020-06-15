#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

function retry () {
  for _ in {1..9}; do
    "$@" && return
    sleep 30
  done
  "$@"
}

function tc-get-secret () {
  TASKCLUSTER_ROOT_URL="${TASKCLUSTER_PROXY_URL-$TASKCLUSTER_ROOT_URL}" retry taskcluster api secrets get "project/fuzzing/$1"
}

# Get the deploy key for langfuzz-config from Taskcluster
tc-get-secret deploy-langfuzz-config | jshon -e secret -e key -u > /root/.ssh/id_rsa.langfuzz-config
chmod 0600 /root/.ssh/id_rsa.*

# Config and run the logging service
mkdir -p /etc/google/auth /var/lib/td-agent-bit/pos
tc-get-secret google-logging-creds | jshon -e secret -e key > /etc/google/auth/application_default_credentials.json
chmod 0600 /etc/google/auth/application_default_credentials.json
/opt/td-agent-bit/bin/td-agent-bit -c /etc/td-agent-bit/td-agent-bit.conf

# set sysctls defined in setup.sh
sysctl --load /etc/sysctl.d/60-langfuzz.conf

# Setup Key Identities
cat << EOF > /root/.ssh/config

Host langfuzz-config
Hostname github.com
IdentityFile /root/.ssh/id_rsa.langfuzz-config
EOF

# -----------------------------------------------------------------------------

cd /home/ubuntu

# Checkout the configuration with bootstrap script
retry git clone -v --depth 1 git@langfuzz-config:MozillaSecurity/langfuzz-config.git config

# Call bootstrap script
./config/aws/setup-dynamic.sh

# sleep to keep docker container running
set +x
while true; do
  sleep 60
done
