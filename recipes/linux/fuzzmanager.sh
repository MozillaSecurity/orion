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

#### Install FuzzManager

case "${1-install}" in
  install)
    sys-embed \
      ca-certificates \
      python3 \
      python3-distutils
    apt-install-auto \
      gcc \
      git \
      python3-dev \
      python3-pip \
      python3-setuptools \
      python3-wheel

    retry pip3 install boto
    if [ "$EDIT" = "1" ]
    then
      cd "${DESTDIR-/home/worker}"
      git-clone https://github.com/MozillaSecurity/FuzzManager fuzzmanager
      retry pip3 install --no-build-isolation -e ./fuzzmanager
    else
      retry pip3 install "git+https://github.com/MozillaSecurity/FuzzManager"
    fi
    ;;
  test)
    python3 -m Collector --help
    ;;
esac
