#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source /home/worker/.local/bin/common.sh

get-tc-secret google-logging-creds /etc/google/auth/application_default_credentials.json raw
mkdir -p /etc/td-agent-bit
cat > /etc/td-agent-bit/td-agent-bit.conf << EOF
[SERVICE]
    Daemon       On
    Log_File     /var/log/td-agent-bit.log
    Log_Level    info
    Parsers_File parsers.conf
    Plugins_File plugins.conf

[INPUT]
    Name tail
    Path /logs/live.log,/home/worker/grizzly-auto-run/screenlog.*
    Path_Key file
    Key message
    Refresh_Interval 5
    Read_from_Head On
    Skip_Long_Lines On
    Buffer_Max_Size 1M
    DB /var/lib/td-agent-bit/pos/grizzly-logs.pos
    DB.locking true

[FILTER]
    Name rewrite_tag
    Match tail.*
    Rule \$file screenlog.([0-9]+)$ screen\$1.log false
    Rule \$file ([^/]+)$ \$1 false

[FILTER]
    Name record_modifier
    Match *
    Record host $(relative-hostname)
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

# shellcheck disable=SC2317
function onexit () {
  echo "Waiting for logs to flush..." >&2
  sleep 15
  killall -INT td-agent-bit || true
  sleep 15
}
trap onexit EXIT

wait_token="$(su worker -c "rwait create")"
su worker -c "/home/worker/launch-grizzly-worker.sh '$wait_token'"

# need to keep the container running
set +e
rwait wait "$wait_token"
exit_code=$?
echo "returned $exit_code" >&2
case $exit_code in
  5)  # grizzly.common.utils.Exit
      # expected results not reproduced (opposite of SUCCESS)
    exit 0
    ;;
  4)  # grizzly.common.utils.LAUNCH_FAILURE
      # unrelated target failure (browser startup crash, etc)
    exit 0
    ;;
  *)
    exit $exit_code
    ;;
esac
