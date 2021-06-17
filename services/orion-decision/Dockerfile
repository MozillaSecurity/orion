# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM alpine:latest

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

COPY services/orion-decision /src/orion-decision
RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="$((i+1))"; done; "$@"; } \
    && retry apk add --no-cache build-base git python3 py3-pip py3-wheel python3-dev py3-requests py3-setuptools py3-six \
    && ln -s /usr/bin/python3 /usr/bin/python \
    && retry pip --no-cache-dir --disable-pip-version-check install -e /src/orion-decision \
    && find /usr/lib/python*/site-packages -name "*.so" -exec strip {} \; \
    && apk del build-base py3-pip py3-wheel python3-dev \
    && python -m compileall -b -q /usr/lib \
    && find /usr/lib -name \*.py -delete \
    && find /usr/lib -name __pycache__ -exec rm -rf \{\} +

CMD ["decision"]
