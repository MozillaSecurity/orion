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

#### Install recipes

cd "${0%/*}"
./taskcluster.sh
PIP_BREAK_SYSTEM_PACKAGES=1 ./gsutil.sh

packages=(
    binutils
    clang
    curl
    git
    gyp
    jshon
    libclang-rt-dev
    libssl-dev
    locales
    make
    mercurial
    ninja-build
    openssh-client
    python-is-python3
    python3
    strace
    unzip
    zlib1g-dev
)

sys-embed "${packages[@]}"

#### Base System Configuration

# Generate locales
locale-gen en_US.utf8

#### Base Environment Configuration

mkdir -p /home/worker/.local/bin

# Add `cleanup.sh` to let images perform standard cleanup operations.
cp "${0%/*}/cleanup.sh" /home/worker/.local/bin/cleanup.sh

# Add shared `common.sh` to Bash
cp "${0%/*}/common.sh" /home/worker/.local/bin/common.sh
printf "source ~/.local/bin/common.sh\n" >> /home/worker/.bashrc

/home/worker/.local/bin/cleanup.sh

mkdir -p /home/worker/.ssh
retry ssh-keyscan github.com > /home/worker/.ssh/known_hosts

chown -R worker:worker /home/worker
chmod 0777 /src
