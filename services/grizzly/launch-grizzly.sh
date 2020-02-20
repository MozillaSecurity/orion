#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

su worker -c /home/worker/launch-grizzly-worker.sh

# need to keep the container running
while true; do
  if [[ -n "$EC2SPOTMANAGER_PROVIDER" || -n "$TASKCLUSTER_PROXY_URL" ]]; then
    # this will fail if we aren't in the cloud
    /usr/local/bin/screenlog-to-cloudwatch.py || true
  fi
  sleep 60
done
