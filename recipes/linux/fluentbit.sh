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

#### Install fluentbit logging agent

case "${1-install}" in
  install)
    apt-install-auto \
      ca-certificates \
      curl \
      gpg \
      gpg-agent \
      lsb-release

    if [[ ! -f /etc/apt/sources.list.d/fluentbit.list ]]; then
      keypath="$(install-apt-key https://packages.fluentbit.io/fluentbit.key)"
      cat > /etc/apt/sources.list.d/fluentbit.list <<- EOF
	deb [signed-by=${keypath}] https://packages.fluentbit.io/ubuntu/$(lsb_release -sc) $(lsb_release -sc) main
	EOF

      sys-update
    fi

    sys-embed td-agent-bit
    ;;
  test)
    /opt/td-agent-bit/bin/td-agent-bit --help
    /opt/td-agent-bit/bin/td-agent-bit --version
    ;;
esac
