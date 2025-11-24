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

#### Install llvm-cov

case "${1-install}" in
  install)
    VERSION=20 "${0%/*}/llvm.sh" setup

    apt-install-auto llvm-20
    apt-mark manual libcurl4 libllvm20

    ln -L /usr/bin/llvm-cov-20 /usr/local/bin/llvm-cov
    ln -s /usr/local/bin/llvm-cov /usr/local/bin/gcov
    ;;
  test)
    llvm-cov --help
    llvm-cov --version
    ;;
esac
