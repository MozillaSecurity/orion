#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source /src/recipes/common.sh

if [[ -n $SENTRY_DSN ]]; then
  export SENTRY_CLI_NO_EXIT_TRAP=1
  # eval "$(sentry-cli bash-hook)"
fi

if [[ -n $TASK_ID ]] || [[ -n $RUN_ID ]]; then
  TARGET_TIME="$(($(get-deadline) - $(date +%s) - 5 * 60))"
else
  TARGET_TIME=$((10 * 365 * 24 * 3600))
fi

# Get the deploy key for langfuzz-config from Taskcluster
get-tc-secret deploy-langfuzz-config /root/.ssh/id_rsa.langfuzz-config

# Config and run the logging service
mkdir -p /etc/google/auth /var/lib/td-agent-bit/pos
get-tc-secret google-logging-creds /etc/google/auth/application_default_credentials.json raw
/opt/td-agent-bit/bin/td-agent-bit -c /etc/td-agent-bit/td-agent-bit.conf

function onexit() {
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
cat <<EOF >/root/.ssh/config

Host langfuzz-config
Hostname github.com
IdentityFile /root/.ssh/id_rsa.langfuzz-config
EOF

# -----------------------------------------------------------------------------

cd /home/ubuntu

pushd /src/fuzzmanager >/dev/null
retry git fetch -q --depth 1 --no-tags origin master
git reset --hard origin/master
popd >/dev/null

# Checkout the configuration with bootstrap script
retry git clone -v --depth 1 git@langfuzz-config:MozillaSecurity/langfuzz-config.git config

# Call bootstrap script
./config/aws/setup-dynamic.sh

# sleep to keep docker container running
echo "[$(date -u -Iseconds)] waiting ${TARGET_TIME}s"
sleep $TARGET_TIME
echo "[$(date -u -Iseconds)] ${TARGET_TIME}s elapsed, exiting..."
