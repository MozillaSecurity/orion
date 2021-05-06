#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source ~worker/.local/bin/common.sh

if [[ "$(id -u)" = "0" ]]
then
  if [[ -z "$NO_SECRETS" ]]
  then
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
    Path /logs/live.log,/home/worker/screenlog.*
    Path_Key file
    Key message
    Refresh_Interval 5
    Read_from_Head On
    Skip_Long_Lines On
    Buffer_Max_Size 1M
    DB /var/lib/td-agent-bit/pos/libfuzzer-logs.pos
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

    function onexit () {
      echo "Waiting for logs to flush..." >&2
      sleep 15
      killall -INT td-agent-bit
      sleep 15
    }

    trap onexit EXIT
  fi
  # These sysctls shouldn't be necessary for libFuzzer
  # sysctl --load /etc/sysctl.d/60-fuzzos.conf
  su worker -c "$0"
else
  if [[ $COVERAGE ]]
  then

    if [[ -z "$TASK_ID" ]]
    then
      function onexit {
        disable-ec2-pool || true
      }

      trap onexit EXIT
    fi

    echo "Launching coverage LibFuzzer run."
    ./coverage.sh
  else
    echo "Launching LibFuzzer run."
    ./libfuzzer.sh
  fi
fi
