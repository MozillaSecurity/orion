#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

#### Cleanup Artifacts

retry () {
  i=0
  while [ $i -lt 9 ]
  do
    # shellcheck disable=SC2015
    "$@" && return || sleep 30
    i="${i+1}"
  done
  "$@"
}

retry rm -rf /usr/share/man/ /usr/share/info/
retry find /usr/share/doc -depth -type f ! -name copyright -exec rm {} +
retry find /usr/share/doc -empty -exec rmdir {} +
retry apt-get clean -y
retry apt-get autoremove --purge -y
retry rm -rf /var/lib/apt/lists/*
retry rm -rf /var/log/*
retry rm -rf /root/.cache/*
retry rm -rf /tmp/*
