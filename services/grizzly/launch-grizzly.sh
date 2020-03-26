#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

wait_token="$(su worker -c "rwait create")"
su worker -c "/home/worker/launch-grizzly-worker.sh '$wait_token'"

if [ -n "$PAPERTRAIL_HOST" ] && [ -n "$PAPERTRAIL_PORT" ]; then
  cat > /etc/log_files.yml << EOF
files:
 - /logs/live.log
 - /home/worker/grizzly-auto-run/screenlog.*
destination:
  host: $PAPERTRAIL_HOST
  port: $PAPERTRAIL_PORT
  protocol: tls
EOF
  remote_syslog
fi

if [ -z "$PAPERTRAIL_HOST" ] && [ -n "$EC2SPOTMANAGER_PROVIDER" ]; then
  /usr/local/bin/screenlog-to-cloudwatch.py &
fi

# need to keep the container running
exec rwait wait "$wait_token"
