#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -u

USER="$1"
IMAGE="$2"

docker manifest create \
  "$USER/$IMAGE":latest \
  "$USER/$IMAGE":amd64-latest \
  "$USER/$IMAGE":arm64-latest

docker manifest annotate "$USER/$IMAGE":latest "$USER/$IMAGE":amd64-latest --os linux --arch amd64
docker manifest annotate "$USER/$IMAGE":latest "$USER/$IMAGE":arm64-latest --os linux --arch arm64 --variant v8

docker manifest push -p "$USER/$IMAGE":latest

docker manifest inspect "$USER/$IMAGE":latest
