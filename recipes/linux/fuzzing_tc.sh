#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# supports-test /force-deps=fuzzing-decision

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

case "${1-install}" in
  install)
    # assert that SRCDIR is set
    [ -n "$SRCDIR" ]

    sys-embed \
      ca-certificates \
      git \
      openssh-client \
      python3 \
      python3-setuptools
    apt-install-auto \
      gcc \
      python3-dev \
      python3-pip \
      python3-wheel

    if [ "$EDIT" = "1" ]
    then
      retry pip3 install -e "$SRCDIR"
    else
      retry pip3 install "$SRCDIR"
    fi
    ;;
  test)
    fuzzing-pool-launch --help
    ;;
esac
