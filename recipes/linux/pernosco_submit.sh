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

#### Install pernosco-submit

case "${1-install}" in
  install)
    sys-embed \
      ca-certificates \
      openssl \
      python3 \
      zstd
    apt-install-auto \
      curl \
      gcc \
      python3-dev \
      python3-pip \
      python3-setuptools \
      python3-wheel
    retry pip3 install awscli

    curl --retry 5 -sL "https://raw.githubusercontent.com/Pernosco/pernosco-submit/master/pernosco-submit" -o /usr/local/bin/pernosco-submit
    chmod +x /usr/local/bin/pernosco-submit
    ;;
  test)
    pernosco-submit --help
    ;;
esac
