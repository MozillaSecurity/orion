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

packages=(
  libasound2:i386
  libatk1.0-0:i386
  libatomic1:i386  # needed only on 22.04
  libc6:i386
  libcairo-gobject2:i386
  libcairo2:i386
  libcanberra0:i386
  libdbus-1-3:i386
  libdbus-glib-1-2:i386
  libffi7:i386
  libfontconfig1:i386
  libfreetype6:i386
  libgcc-s1:i386
  libgdk-pixbuf2.0-0:i386
  libglib2.0-0:i386
  libgtk-3-0:i386
  libharfbuzz0b:i386
  libpango-1.0-0:i386
  libpangocairo-1.0-0:i386
  libpangoft2-1.0-0:i386
  libstdc++6:i386
  libx11-6:i386
  libx11-xcb1:i386
  libxcb-shm0:i386
  libxcb1:i386
  libxcomposite1:i386
  libxcursor1:i386
  libxdamage1:i386
  libxext6:i386
  libxfixes3:i386
  libxi6:i386
  libxrandr2:i386
  libxrender1:i386
  libxt6:i386
  libxtst6:i386
)

case "${1-install}" in
  install)
    dpkg --add-architecture i386
    sys-update
    apt-install-auto apt-utils
    sys-embed "${packages[@]}"
    ;;
  test)
    sys-update
    "${0%/*}/fuzzfetch.sh"
    TMPD="$(mktemp -d -p. ff32.test.XXXXXXXXXX)"
    pushd "$TMPD" >/dev/null
      fuzzfetch --name obj --target firefox --cpu x86
      ./obj/firefox --help
    popd >/dev/null
    rm -rf "$TMPD"
    "${0%/*}/fuzzfetch.sh" uninstall
    "${0%/*}/cleanup.sh"
    ;;
esac
