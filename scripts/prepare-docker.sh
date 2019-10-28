#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -u

update_docker_configuration() {
  echo "INFO: Updating Docker CLI configuration ..."
  mkdir -p ~/.docker
  echo '{"experimental": "enabled"}' | tee ~/.docker/config.json

  echo "INFO: Updating Docker Daemon configuration ..."
  echo '{"experimental": true}' | sudo tee /etc/docker/daemon.json

  # "storage-driver": "overlay2"
  # "max-concurrent-downloads": 50
  # "max-concurrent-uploads": 50

  sudo service docker restart
}

update_docker_configuration
