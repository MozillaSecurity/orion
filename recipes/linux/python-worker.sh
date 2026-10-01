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

python -m venv /tmp/venv/pipx
retry /tmp/venv/pipx/bin/pip install pipx
PIPX_DEFAULT_PYTHON="$(which python)"
export PIPX_DEFAULT_PYTHON

py_packages=(mercurial poetry)

for pkg in "${py_packages[@]}"; do
  retry /tmp/venv/pipx/bin/pipx install --global "$pkg"
done

#### Install recipes

"${0%/*}/worker.sh"
"${0%/*}/cleanup.sh"

mkdir /home/worker/.ssh
retry ssh-keyscan github.com >/home/worker/.ssh/known_hosts

chown -R worker:worker /home/worker
chmod 0777 /src
