# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM python:3.9-alpine

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

COPY base/linux/etc/pip.conf /etc/pip.conf

WORKDIR /root

RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="${i+1}"; done; "$@"; } \
    && retry apk add --no-cache bash curl jq \
    && retry pip -q install fuzzfetch

COPY recipes/linux/common.sh /root/.local/bin/common.sh
COPY services/coverage-revision/launch.sh /root/launch.sh
CMD ["/root/launch.sh"]
