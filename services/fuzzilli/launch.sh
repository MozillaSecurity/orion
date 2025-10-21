#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source /home/ubuntu/.local/bin/common.sh

if [[ "$(id -u)" == "0" ]]; then
  if [[ -n $SENTRY_DSN ]]; then
    export SENTRY_CLI_NO_EXIT_TRAP=1
    # eval "$(sentry-cli bash-hook)"
  fi

  # Config and run the logging service
  mkdir -p /etc/google/auth /var/lib/td-agent-bit/pos
  get-tc-secret google-logging-creds /etc/google/auth/application_default_credentials.json raw
  /opt/td-agent-bit/bin/td-agent-bit -c /etc/td-agent-bit/td-agent-bit.conf

  function onexit() {
    echo "Saving ~/work to /logs/work.tar.zst" >&2
    #tar -C /home/ubuntu -c work | zstd -f -o /logs/work.tar.zst
    #tar -c /home/ubuntu | zstd -f -o /logs/work.tar.zst
    echo "Waiting for logs to flush..." >&2
    sleep 15
    killall -INT td-agent-bit || true
    sleep 15
    #cp /home/ubuntu/* /logs/
  }
  trap onexit EXIT

  su ubuntu -c "$0"
else
  echo "Launching fuzzilli run."
  ./fuzzilli.sh
fi
