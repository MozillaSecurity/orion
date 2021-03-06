#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# supports-test

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Install gsutil

case "${1-install}" in
  install)
    sys-embed \
      python3 \
      python3-setuptools \
      zstd
    apt-install-auto \
      gcc \
      python3-dev \
      python3-pip \
      python3-wheel

    retry pip3 install gsutil
    ;;
  test)
    gsutil version
    ;;
esac
