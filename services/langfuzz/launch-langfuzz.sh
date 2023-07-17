#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

function retry () {
  op="$(mktemp)"
  for _ in {1..9}; do
    if "$@" >"$op"; then
      cat "$op"
      rm "$op"
      return
    fi
    sleep 30
  done
  rm "$op"
  "$@"
}

function tc-get-secret () {
  TASKCLUSTER_ROOT_URL="${TASKCLUSTER_PROXY_URL-$TASKCLUSTER_ROOT_URL}" retry taskcluster api secrets get "project/fuzzing/$1"
}

if [[ -n "$TASK_ID" ]] || [[ -n "$RUN_ID" ]] ; then
  function get-deadline () {
    tmp="$(mktemp -d)"
    retry taskcluster api queue task "$TASK_ID" >"$tmp/task.json"
    retry taskcluster api queue status "$TASK_ID" >"$tmp/status.json"
    deadline="$(date --date "$(jshon -e status -e deadline -u <"$tmp/status.json")" +%s)"
    started="$(date --date "$(jshon -e status -e runs -e "$RUN_ID" -e started -u <"$tmp/status.json")" +%s)"
    max_run_time="$(jshon -e payload -e maxRunTime -u <"$tmp/task.json")"
    rm -rf "$tmp"
    run_end="$((started + max_run_time))"
    if [[ $run_end -lt $deadline ]]; then
      echo "$run_end"
    else
      echo "$deadline"
    fi
  }
  TARGET_TIME="$(($(get-deadline) - $(date +%s) - 5 * 60))"
else
  TARGET_TIME=$((10 * 365 * 24 * 3600))
fi

# Get the deploy key for langfuzz-config from Taskcluster
tc-get-secret deploy-langfuzz-config | jshon -e secret -e key -u > /root/.ssh/id_rsa.langfuzz-config
chmod 0600 /root/.ssh/id_rsa.*

# Config and run the logging service
mkdir -p /etc/google/auth /var/lib/td-agent-bit/pos
tc-get-secret google-logging-creds | jshon -e secret -e key > /etc/google/auth/application_default_credentials.json
chmod 0600 /etc/google/auth/application_default_credentials.json
/opt/td-agent-bit/bin/td-agent-bit -c /etc/td-agent-bit/td-agent-bit.conf

function onexit () {
  echo "Saving ~/work to /logs/work.tar.zst" >&2
  tar -C /home/ubuntu -c work | zstd -f -o /logs/work.tar.zst
  echo "Waiting for logs to flush..." >&2
  sleep 15
  killall -INT td-agent-bit || true
  sleep 15
}
trap onexit EXIT

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
echo "[$(date -u -Iseconds)] waiting ${TARGET_TIME}s"
sleep $TARGET_TIME
echo "[$(date -u -Iseconds)] ${TARGET_TIME}s elapsed, exiting..."
