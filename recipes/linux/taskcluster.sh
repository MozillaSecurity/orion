#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# supports-test

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Install Taskcluster CLI

case "${1-install}" in
  install)
    apt-install-auto \
        ca-certificates \
        curl

    TC_VERSION="$(curl --retry 5 -s "https://github.com/taskcluster/taskcluster/releases/latest" | sed 's/.\+\/tag\/\(.\+\)".\+/\1/')"
    curl --retry 5 -sSL "https://github.com/taskcluster/taskcluster/releases/download/${TC_VERSION}/taskcluster-linux-amd64" -o /usr/local/bin/taskcluster
    chmod +x /usr/local/bin/taskcluster
    ;;
  test)
    taskcluster version
    ;;
esac
