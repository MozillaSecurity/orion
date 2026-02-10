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

#### Install FuzzFetch

case "${1-install}" in
  install)
    sys-embed \
      ca-certificates \
      lbzip2 \
      python3 \
      xz-utils \
      zstd
    apt-install-auto \
      git \
      pipx

    if [[ $EDIT == "1" ]]; then
      cd "${DESTDIR-/home/worker}"
      git-clone https://github.com/MozillaSecurity/fuzzfetch fuzzfetch
      PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin retry pipx install -e "./fuzzfetch[sentry]"
    else
      PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin retry pipx install "fuzzfetch[sentry] @ git+https://github.com/MozillaSecurity/fuzzfetch.git"
    fi
    ;;
  test)
    fuzzfetch -h
    ;;
esac
