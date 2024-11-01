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

sys-update

packages=(
  bzip2
  curl
  gcc
  git
  jshon
  libc6-dev
  libffi-dev
  libssl-dev
  make
  openssh-client
  patch
  xz-utils
)

sys-update
sys-embed "${packages[@]}"

py_packages=(
  mercurial
  poetry
  pre-commit
  tox
)

retry pip install "${py_packages[@]}"
retry-curl https://uploader.codecov.io/latest/linux/codecov -o /usr/local/bin/codecov
chmod +x /usr/local/bin/codecov

#### Install recipes

SRCDIR=/src/orion-decision EDIT=1 "${0%/*}/orion_decision.sh"
"${0%/*}/worker.sh"
"${0%/*}/cleanup.sh"

mkdir /home/worker/.ssh
retry ssh-keyscan github.com > /home/worker/.ssh/known_hosts

chown -R worker:worker /home/worker
chmod 0777 /src
