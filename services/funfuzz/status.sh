#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# shellcheck source=recipes/linux/common.sh
source ~/.local/bin/common.sh

function stats () {
  uptime
  free -m
  df -h
}
while true; do
  update-ec2-stats "$(stats)" || true
  sleep 60
done
