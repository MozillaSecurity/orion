#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source ~worker/.local/bin/common.sh

function on-exit {
  echo "Script is terminating - executing trap commands."
  if [[ $COVERAGE ]]
  then
    disable-ec2-pool || true
  fi
  if [[ -z "$NO_LOGS" ]]
  then
    echo "Waiting for logs to flush..." >&2
    sleep 10
  fi
}

if [[ "$(id -u)" = "0" ]]
then
  if [[ -z "$NO_CREDSTASH" ]]
  then
    # In some environments, we require credentials for talking to credstash
    su worker -c ". ~/.local/bin/common.sh && setup-aws-credentials '$SHIP'"
    mkdir -p /etc/google/auth /etc/td-agent-bit
    su worker -c ". ~/.local/bin/common.sh && retry credstash get google-logging-creds.json" > /etc/google/auth/application_default_credentials.json
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
    Buffer_Max_Size 1M
    DB /var/lib/td-agent-bit/pos/libfuzzer-logs.pos

[FILTER]
    Name rewrite_tag
    Match tail.*
    Rule \$file ([^/]+)$ \$1 false

[FILTER]
    Name record_modifier
    Match *
    Record host $(relative-hostname "$SHIP")
    Record pool ${EC2SPOTMANAGER_POOLID-${TASKCLUSTER_FUZZING_POOL-unknown}}
    Remove_key file

[OUTPUT]
    Name stackdriver
    Match *
    google_service_credentials /etc/google/auth/application_default_credentials.json
    resource global
EOF
    mkdir -p /var/lib/td-agent-bit/pos
    /opt/td-agent-bit/bin/td-agent-bit -c /etc/td-agent-bit/td-agent-bit.conf
  fi
  # These sysctls shouldn't be necessary for libFuzzer
  # sysctl --load /etc/sysctl.d/60-fuzzos.conf
  su worker -c "$0"
else
  trap on-exit EXIT ERR
  if [[ $COVERAGE ]]
  then
    echo "Launching coverage LibFuzzer run."
    ./coverage.sh
  else
    echo "Launching LibFuzzer run."
    ./libfuzzer.sh
  fi
fi
