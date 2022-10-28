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
./fluentbit.sh
./fuzzfetch.sh
EDIT=1 SRCDIR=/src/fuzzing-tc ./fuzzing_tc.sh
./fuzzmanager.sh
./grcov.sh
./taskcluster.sh

packages=(
  binutils curl gyp jshon libgcc-9-dev libssl-dev libstdc++-9-dev libxml2 locales make mercurial ninja-build python-is-python3 python3 python3-yaml zlib1g-dev zstd
)

sys-embed "${packages[@]}"

#### Base System Configuration

# Generate locales
locale-gen en_US.utf8

#### Base Environment Configuration

cat << 'EOF' >> /home/worker/.bashrc

# FuzzOS
export PS1='🐳  \[\033[1;36m\]\h \[\033[1;34m\]\W\[\033[0;35m\] \[\033[1;36m\]λ\[\033[0m\] '
EOF

mkdir -p /home/worker/.local/bin

# Add `cleanup.sh` to let images perform standard cleanup operations.
cp "${0%/*}/cleanup.sh" /home/worker/.local/bin/cleanup.sh

# Add shared `common.sh` to Bash
cp "${0%/*}/common.sh" /home/worker/.local/bin/common.sh
printf "source ~/.local/bin/common.sh\n" >> /home/worker/.bashrc

/home/worker/.local/bin/cleanup.sh

mkdir -p /home/worker/.ssh /root/.ssh
chmod 0700 /home/worker/.ssh /root/.ssh
cat << EOF | tee -a /root/.ssh/config /home/worker/.ssh/config > /dev/null
Host *
UseRoaming no
EOF
retry ssh-keyscan github.com | tee -a /root/.ssh/known_hosts /home/worker/.ssh/known_hosts > /dev/null

chown -R worker:worker /home/worker
chmod 0777 /src
