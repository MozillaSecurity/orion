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

#### Install LLVM

VERSION=16

if [[ $1 == "auto" ]]; then
  function install-auto-arg() {
    apt-install-auto "$@"
  }
  shift
else
  function install-auto-arg() {
    sys-embed "$@"
  }
fi

case "${1-install}" in
  install | setup)
    apt-install-auto \
      ca-certificates \
      curl \
      gpg \
      gpg-agent \
      lsb-release

    if [[ ! -f /etc/apt/sources.list.d/llvm.list ]]; then
      keypath="$(install-apt-key https://apt.llvm.org/llvm-snapshot.gpg.key)"
      cat >/etc/apt/sources.list.d/llvm.list <<-EOF
	deb [signed-by=${keypath}] https://apt.llvm.org/$(lsb_release -cs)/ llvm-toolchain-$(lsb_release -cs)-$VERSION main
	EOF

      sys-update
    fi

    if [[ $1 == "setup" ]]; then
      exit
    fi

    install-auto-arg \
      "clang-$VERSION" \
      "llvm-$VERSION" \
      "lld-$VERSION" \
      "lldb-$VERSION" \
      "libfuzzer-$VERSION-dev" \
      "libc++-$VERSION-dev" "libc++abi-$VERSION-dev"

    update-alternatives --install \
      /usr/bin/llvm-config llvm-config "/usr/bin/llvm-config-$VERSION" 100 \
      --slave /usr/bin/clang clang "/usr/bin/clang-$VERSION" \
      --slave /usr/bin/clang++ clang++ "/usr/bin/clang++-$VERSION" \
      --slave /usr/bin/llvm-symbolizer llvm-symbolizer "/usr/bin/llvm-symbolizer-$VERSION" \
      --slave /usr/bin/lldb lldb "/usr/bin/lldb-$VERSION"
    ;;
  test)
    clang --version
    llvm-symbolizer --version
    ;;
esac
