# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM python:3.9-alpine

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

COPY base/linux/etc/pip.conf /etc/pip.conf

WORKDIR /root

RUN retry () { i=0; while [ $i -lt 9 ]; do if "$@"; then return; else sleep 30; fi; i="$((i+1))"; done; "$@"; } \
    && retry apk add --no-cache bash curl \
    && retry pip install --disable-pip-version-check --no-cache-dir --progress-bar off fuzzfetch

COPY services/coverage-revision/launch.sh /root/launch.sh
CMD ["/root/launch.sh"]
