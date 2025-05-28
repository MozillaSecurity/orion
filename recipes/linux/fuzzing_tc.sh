#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# supports-test /force-dirty=fuzzing-decision

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

case "${1-install}" in
  install)
    # assert that SRCDIR is set
    [[ -n $SRCDIR ]]

    sys-embed \
      ca-certificates \
      git \
      openssh-client \
      python3
    apt-install-auto \
      pipx

    if [[ $EDIT == "1" ]]; then
      PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin retry pipx install -e "$SRCDIR"
    else
      PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin retry pipx install "$SRCDIR"
    fi
    ;;
  test)
    fuzzing-pool-launch --help
    ;;
esac
