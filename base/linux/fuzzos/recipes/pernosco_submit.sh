#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=base/linux/fuzzos/recipes/common.sh
source "${0%/*}/common.sh"

#### Install pernosco-submit

apt-install-auto \
  zstd

git clone --depth 1 --no-tags https://github.com/Pernosco/pernosco-submit.git

pip3 install awscli
