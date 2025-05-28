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
      git \
      pipx \
      python3-venv
    PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin retry pipx install awscli
    python3 -m venv /opt/venvs/pernosco

    python_path="$(/opt/venvs/pernosco/bin/python3 -c 'import distutils.sysconfig;print(distutils.sysconfig.get_python_lib())')"
    TMPD="$(mktemp -d -p. pernosco.build.XXXXXXXXXX)"
    pushd "$TMPD" >/dev/null
    git-clone "https://github.com/pernosco/pernosco-submit"
    cp -r pernosco-submit/pernoscoshared "$python_path"
    cp pernosco-submit/pernosco-submit /usr/local/bin
    popd >/dev/null
    rm -rf "$TMPD"
    sed -i '1 s,^.*$,#!/opt/venvs/pernosco/bin/python3,' /usr/local/bin/pernosco-submit
    chmod +x /usr/local/bin/pernosco-submit
    ;;
  test)
    pernosco-submit --help
    aws --version
    openssl version
    zstdmt --version
    ;;
esac
