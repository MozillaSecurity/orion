#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

function retry () {
  # shellcheck disable=SC2015
  for _ in {1..9}; do
    "$@" && return || sleep 30
  done
  "$@"
}

# Get the deploy key for langfuzz-config from Taskcluster
retry taskcluster api secrets get project/fuzzing/deploy-langfuzz-config | jshon -e secret -e key -u > /root/.ssh/id_rsa.langfuzz-config
chmod 0600 /root/.ssh/id_rsa.*

mkdir -p /etc/google/auth /etc/td-agent-bit
retry taskcluster api secrets get project/fuzzing/google-logging-creds | jshon -e secret -e key > /etc/google/auth/application_default_credentials.json
chmod 0600 /etc/google/auth/application_default_credentials.json
cat > /etc/td-agent-bit/td-agent-bit.conf << EOF
[SERVICE]
    Flush        5
    Daemon       On
    Log_File     /var/log/td-agent-bit.log
    Log_Level    info
    Parsers_File parsers.conf
    Plugins_File plugins.conf
    HTTP_Server  Off

[INPUT]
    Name tail
    Path /logs/live.log
    Path_Key file
    Key message
    DB /var/lib/td-agent-bit/pos/langfuzz-logs.pos

[INPUT]
    Name tail
    Path /home/ubuntu/screenlog.*
    Path_Key file
    Key message
    DB /var/lib/td-agent-bit/pos/langfuzz-logs.pos

[FILTER]
    Name rewrite_tag
    Match tail.*
    Rule \$file ([^/]+)$ \$1 false

[FILTER]
    Name record_modifier
    Match *
    Record host task-${TASK_ID}-run-${RUN_ID}
    Record pool ${TASKCLUSTER_FUZZING_POOL-unknown}
    Remove_key file

[OUTPUT]
    Name stackdriver
    Match *
    google_service_credentials /etc/google/auth/application_default_credentials.json
    resource global
EOF
mkdir -p /var/lib/td-agent-bit/pos
/opt/td-agent-bit/bin/td-agent-bit -c /etc/td-agent-bit/td-agent-bit.conf

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

while true; do
  sleep 60
done
