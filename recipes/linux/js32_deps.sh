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

if ! is-arm64; then
  echo "Not arm64. Installing 32 bit packages."
  packages+=(
        lib32z1
        lib32z1-dev
        libc6-dbg:i386
        g++-multilib
        gcc-multilib
  )
  case "${1-install}" in
    install)
      dpkg --add-architecture i386
      sys-update
      apt-install-auto apt-utils
      sys-embed libatomic1:i386 libstdc++6:i386 libnspr4:i386
      ;;
    test)
      sys-update
      "${0%/*}/fuzzfetch.sh"
      TMPD="$(mktemp -d -p. js32.test.XXXXXXXXXX)"
      pushd "$TMPD" >/dev/null
        fuzzfetch --name jsshell --target js --cpu x86
        ./jsshell/dist/bin/js --help
      popd >/dev/null
      rm -rf "$TMPD"
      "${0%/*}/fuzzfetch.sh" uninstall
      "${0%/*}/cleanup.sh"
      ;;
  esac
else
  echo "Is arm64. Skipping 32 bit packages."
  sys-update
  apt-install-auto apt-utils
fi
