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
apt-install-auto \
  ca-certificates \
  gpg \
  gpg-agent \
  lsb-release
sys-embed \
  curl \
  git \
  openssh-client

retry-curl https://apt.corretto.aws/corretto.key | gpg --dearmor -o /etc/apt/keyrings/corretto.gpg
echo "deb [signed-by=/etc/apt/keyrings/corretto.gpg] https://apt.corretto.aws stable main" >/etc/apt/sources.list.d/corretto.list
sys-update

mkdir /opt/maven
retry-curl https://archive.apache.org/dist/maven/maven-3/3.9.10/binaries/apache-maven-3.9.10-bin.tar.gz | tar -C /opt/maven --strip-components=1 -xz
#shellcheck disable=SC2016
echo 'PATH=$PATH:/opt/maven/bin' >>/etc/bash.bashrc
echo ". /etc/environment" >>/etc/bash.bashrc

#### Install recipes

sys-embed java-11-amazon-corretto-jdk

SRCDIR=/src/orion-decision "${0%/*}/orion_decision.sh"
"${0%/*}/worker.sh"
mkdir /home/worker/.ssh
retry ssh-keyscan github.com >/home/worker/.ssh/known_hosts

chown -R worker:worker /home/worker
chmod 0777 /src

"${0%/*}/cleanup.sh"
