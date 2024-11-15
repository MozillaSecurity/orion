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

#### Install Prefpicker

case "${1-install}" in
  install)
    sys-embed \
      python3
    apt-install-auto \
      git \
      pipx

    if [[ "$EDIT" = "1" ]]
    then
      cd "${DESTDIR-/home/worker}"
      git-clone https://github.com/MozillaSecurity/prefpicker prefpicker
      PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin retry pipx install -e ./prefpicker
    else
      PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin retry pipx install git+https://github.com/MozillaSecurity/prefpicker.git
    fi
    ;;
  test)
    prefpicker -h
    ;;
esac
