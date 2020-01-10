#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=base/linux/fuzzos/recipes/common.sh
source "${0%/*}/common.sh"

#### Install pernosco-submit

sys-embed \
  zstd

curl -L "https://raw.githubusercontent.com/Pernosco/pernosco-submit/master/pernosco-submit" > /usr/local/bin/pernosco-submit
chmod +x /usr/local/bin/pernosco-submit

pip3 install awscli
