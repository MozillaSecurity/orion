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
      git \
      python3-dev \
      python3-pip \
      python3-setuptools \
      python3-wheel
    retry pip3 install awscli

    python_path="$(python3 -c 'import distutils.sysconfig;print(distutils.sysconfig.get_python_lib())')"
    TMPD="$(mktemp -d -p. pernosco.build.XXXXXXXXXX)"
    pushd "$TMPD" >/dev/null
      git-clone "https://github.com/pernosco/pernosco-submit"
      cp -r pernosco-submit/pernoscoshared "$python_path"
      cp pernosco-submit/pernosco-submit /usr/local/bin
    popd >/dev/null
    rm -rf "$TMPD"
    chmod +x /usr/local/bin/pernosco-submit
    ;;
  test)
    pernosco-submit --help
    ;;
esac
