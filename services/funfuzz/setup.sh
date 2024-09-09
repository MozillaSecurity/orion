#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Install recipes

cd "${0%/*}"
./js32_deps.sh  # does the initial sys-update
./fluentbit.sh
./fuzzfetch.sh
SRCDIR=/tmp/fuzzing-tc ./fuzzing_tc.sh
./fuzzmanager.sh
./grcov.sh
./gcov-9.sh
./gsutil.sh
./htop.sh
./taskcluster.sh
./llvm-symbolizer.sh

packages=(
  apt-utils
  binutils
  bzip2
  ca-certificates
  curl
  git
  gpg-agent
  jshon
  lbzip2
  less
  libc6-dbg
  libc6-dbg:i386
  locales
  nano
  openssh-client
  psmisc
  ripgrep
  screen
  software-properties-common
  unzip
  zip
  zstd
)
package_recommends=(
  gdb
  mercurial
  wget
)

sys-embed "${packages[@]}"
# want recommends for these packages
retry apt-get install -y -qq "${package_recommends[@]}"

retry pip3 install python-dateutil

#### Base System Configuration

# Generate locales
locale-gen en_US.utf8

# Ensure the machine uses core dumps with PID in the filename
# https://github.com/moby/moby/issues/11740
cat << EOF | tee /etc/sysctl.d/60-fuzzos.conf > /dev/null
# Ensure that we use PIDs with core dumps
kernel.core_uses_pid = 1
# Allow ptrace of any process
kernel.yama.ptrace_scope = 0
EOF

# Ensure we retry metadata requests in case of glitches
# https://github.com/boto/boto/issues/1868
cat << EOF | tee /etc/boto.cfg > /dev/null
[Boto]
metadata_service_num_attempts = 10
EOF

#### Base Environment Configuration

cat << 'EOF' >> /home/worker/.bashrc

# FuzzOS
export PS1='🐳  \[\033[1;36m\]\h \[\033[1;34m\]\W\[\033[0;35m\] \[\033[1;36m\]λ\[\033[0m\] '
EOF

cat << EOF > /home/worker/.hgrc
[ui]
username = funfuzz
merge = internal:merge
ssh = ssh -C -v

[extensions]
mq =
purge =
rebase =
EOF

mkdir -p /home/worker/.local/bin

# Add `cleanup.sh` to let images perform standard cleanup operations.
ln "${0%/*}/cleanup.sh" /home/worker/.local/bin/cleanup.sh

# Add shared `common.sh` to Bash
ln "${0%/*}/common.sh" /home/worker/.local/bin/common.sh
printf "source ~/.local/bin/common.sh\n" >> /home/worker/.bashrc

/home/worker/.local/bin/cleanup.sh

mkdir -p /home/worker/.ssh /root/.ssh
chmod 0700 /home/worker/.ssh /root/.ssh
cat << EOF | tee -a /root/.ssh/config >> /home/worker/.ssh/config
Host *
UseRoaming no
EOF
retry ssh-keyscan github.com | tee -a /root/.ssh/known_hosts >> /home/worker/.ssh/known_hosts

chown -R worker:worker /home/worker
