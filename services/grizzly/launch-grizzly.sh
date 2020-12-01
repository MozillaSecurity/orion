#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source /home/worker/.local/bin/common.sh

SHIP="$(get-provider)"
su worker -c ". ~/.local/bin/common.sh && setup-aws-credentials '$SHIP'"

mkdir -p /etc/google/auth /etc/td-agent-bit
su worker -c '. ~/.local/bin/common.sh && retry credstash get google-logging-creds.json' > /etc/google/auth/application_default_credentials.json
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
    DB /var/lib/td-agent-bit/pos/grizzly-logs.pos

[INPUT]
    Name tail
    Path /home/worker/grizzly-auto-run/screenlog.*
    Path_Key file
    Key message
    Buffer_Max_Size 1M
    DB /var/lib/td-agent-bit/pos/grizzly-logs.pos

[FILTER]
    Name rewrite_tag
    Match tail.*
    Rule \$file screenlog.([0-9]+)$ screen\$1.log false
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

[OUTPUT]
    Name file
    Match screen*.log
    Path /logs/
    Format template
    Template {time} {message}
EOF
mkdir -p /var/lib/td-agent-bit/pos
/opt/td-agent-bit/bin/td-agent-bit -c /etc/td-agent-bit/td-agent-bit.conf

wait_token="$(su worker -c "rwait create")"
su worker -c "/home/worker/launch-grizzly-worker.sh '$wait_token'"

# need to keep the container running
rwait wait "$wait_token"

killall -INT td-agent-bit
echo "Waiting for logs to flush..." >&2
sleep 10
