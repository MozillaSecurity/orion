#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -u

USER="$1"
IMAGE="$2"

images=(
  "$USER/$IMAGE":latest
)

for arch in amd64 arm64; do
  if docker image inspect "$USER/$IMAGE:$arch-latest" >&/dev/null; then
    images+=("$USER/$IMAGE:$arch-latest")
  fi
done

# shellcheck disable=SC2086
docker manifest create "${images[@]}"

if docker image inspect "$USER/$IMAGE:amd64-latest" >&/dev/null; then
  docker manifest annotate "$USER/$IMAGE":latest "$USER/$IMAGE":amd64-latest --os linux --arch amd64
fi
if docker image inspect "$USER/$IMAGE:arm64-latest" >&/dev/null; then
  docker manifest annotate "$USER/$IMAGE":latest "$USER/$IMAGE":arm64-latest --os linux --arch arm64 --variant v8
fi

# don't actually push the manifest for PRs
if [ -z "$TRAVIS_PULL_REQUEST_BRANCH" ]; then
  docker manifest push -p "$USER/$IMAGE":latest
fi

docker manifest inspect "$USER/$IMAGE":latest
