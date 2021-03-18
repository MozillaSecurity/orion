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

case "${1-install}" in
  install)
    sys-embed locales

    # Create worker user and generate locale
    LANGUAGE="${LANGUAGE-en}"
    LANG="${LANG-en_US.UTF-8}"

    useradd -d /home/worker -s /bin/bash -m worker
    cat <<- EOF >> /etc/environment
	LANGUAGE=${LANGUAGE}
	LANG=${LANG}
	LC_ALL=${LANG}
	EOF

    sed -i "s/# ${LANG}/${LANG}/" /etc/locale.gen
    echo "LANG=${LANG}" > /etc/locale.conf
    locale-gen "$LANG"
    ;;
  test)
    su - worker -c "echo 'hello world'"
    # shellcheck disable=SC2016
    [[ "$(su - worker -c 'echo "$LANGUAGE"')" = "en" ]]
    # shellcheck disable=SC2016
    [[ "$(su - worker -c 'echo "$LANG"')" = "en_US.UTF-8" ]]
    # shellcheck disable=SC2016
    [[ "$(su - root -c 'echo "$LANGUAGE"')" = "en" ]]
    # shellcheck disable=SC2016
    [[ "$(su - root -c 'echo "$LANG"')" = "en_US.UTF-8" ]]
    ;;
esac
