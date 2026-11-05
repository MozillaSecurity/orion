#!/bin/bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

mkdir -p /home/worker/.ssh

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Bootstrap Packages

sys-update
sys-embed \
  ca-certificates \
  curl \
  git \
  jshon \
  openssh-client

# Keep pipx applications on the Python 3.10 interpreter from the base image.
PIPX_DEFAULT_PYTHON="$(command -v python3)"
export PIPX_DEFAULT_PYTHON

#### Install recipes

cd "${0%/*}"
./worker.sh
mkdir -p /home/worker/.local/bin
cp common.sh /home/worker/.local/bin/common.sh
touch /home/worker/.bashrc
printf "source ~/.local/bin/common.sh\n" >>/home/worker/.bashrc
./poetry.sh
./taskcluster.sh
./fuzzmanager.sh

retry ssh-keyscan github.com >/home/worker/.ssh/known_hosts
chmod 600 /home/worker/.ssh/config

./cleanup.sh

# Create logfile
touch /live.log

#### Fix ownership
chown -R worker:worker /live.log
chown -R worker:worker /home/worker
chmod 0777 /src
