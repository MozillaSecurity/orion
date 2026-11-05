#!/bin/bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Bootstrap Packages

export DEBIAN_FRONTEND=noninteractive

sys-update

packages=(
  ca-certificates
  curl
  git
  jshon
  libdbus-glib-1-2
  libgtk-3-0
  libx11-xcb1
  libxt6
  openssh-client
)
sys-embed "${packages[@]}"

#### Install recipes

cd "${0%/*}"
./taskcluster.sh
./worker.sh install

#### Configure SSH

mkdir -p /home/worker/.ssh
retry ssh-keyscan github.com >/home/worker/.ssh/known_hosts
chmod 0600 /home/worker/.ssh/config
chown -R worker:worker /home/worker

#### Clean up

./cleanup.sh
