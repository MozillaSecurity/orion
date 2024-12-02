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
      python3
    apt-install-auto \
      pipx

    # Pin the pyopenssl version as gsutil is currently broken with
    # the most recent version, see:
    # https://github.com/GoogleCloudPlatform/gsutil/issues/1820
    PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin retry pipx install gsutil --pip-args "pyopenssl==24.2.1"
    ;;
  test)
    gsutil version
    ;;
esac
