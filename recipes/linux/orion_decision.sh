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
    [ -n "$SRCDIR" ]

    sys-embed \
      ca-certificates \
      git \
      openssh-client
    apt-install-auto \
      gcc

    # check if we don't have Python 3 at all
    if ! which python3 >/dev/null
    then
      NEED_SYS_PY3=1
    # check if we don't have Python 3.6+
    elif python3 -c "import sys;sys.exit(sys.version_info >= (3, 6))"
    then
      # We'll try installing the Ubuntu Python 3
      # If we have python3 and it's not new enough, it should be installed
      # in /usr/local which will take precedence over the Ubuntu version.
      [[ "$(dirname "$(readlink -e "$(which python3)")")" == "/usr/local/bin" ]]
      NEED_SYS_PY3=1
    else
      NEED_SYS_PY3=0
    fi

    if [[ $NEED_SYS_PY3 -eq 1 ]]
    then
      PY3=/usr/bin/python3
      sys-embed \
        python3 \
        python3-setuptools
      apt-install-auto \
        python3-dev \
        python3-pip \
        python3-wheel
    else
      PY3="$(which python3)"
    fi

    if [[ "$EDIT" = "1" ]]
    then
      retry "$PY3" -m pip install --no-build-isolation -e "$SRCDIR"
    else
      retry "$PY3" -m pip install "$SRCDIR"
    fi
    ;;
  test)
    decision --help
    orion-check --help
    ci-decision --help
    ci-check --help
    ci-launch --help
    ;;
esac
