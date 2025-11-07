# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM python:3.13-alpine

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

COPY base/linux/etc/pip.conf /etc/pip.conf

WORKDIR /root

RUN retry () { i=0; while [ $i -lt 9 ]; do if "$@"; then return; else sleep 30; fi; i="$((i+1))"; done; "$@"; } \
    && retry apk add --no-cache bash build-base curl git linux-headers \
    && retry pip install --disable-pip-version-check --no-cache-dir --progress-bar off "git+https://github.com/MozillaSecurity/fuzzfetch.git#egg=fuzzfetch[sentry]" \
    && apk del build-base git linux-headers

COPY recipes/linux/common.sh services/coverage-revision/launch.sh /root/
CMD ["/root/launch.sh"]
