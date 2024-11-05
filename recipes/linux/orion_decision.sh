#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# supports-test /force-dirty=orion-decision

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

case "${1-install}" in
  install)
    # assert that SRCDIR is set
    [[ -n "$SRCDIR" ]]

    sys-embed \
      ca-certificates \
      git \
      openssh-client

    if ! which python3 >/dev/null; then
      sys-embed python3
    fi
    if ! python3 -c "import ensurepip" 2>/dev/null; then
      apt-install-auto python3-venv
    fi

    tmp="$(mktemp -d)"
    python3 -m venv "$tmp"
    retry "$tmp/bin/pip" install pipx
    PIPX_DEFAULT_PYTHON="$(which python3)"
    export PIPX_DEFAULT_PYTHON

    if [[ "$EDIT" = "1" ]]
    then
      retry "$tmp/bin/pipx" install --global -e "$SRCDIR"
    else
      retry "$tmp/bin/pipx" install --global "$SRCDIR"
    fi

    rm -rf "$tmp"
    ;;
  test)
    decision --help
    orion-check --help
    ci-decision --help
    ci-check --help
    ci-launch --help
    ;;
esac
