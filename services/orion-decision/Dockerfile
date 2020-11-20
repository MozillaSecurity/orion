# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM python:3.9-alpine

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

COPY services/orion-decision /src/orion-decision
RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="$((i+1))"; done; "$@"; } \
    && tar cf /tmp/pylibs-orig.tar /usr/local/lib \
    && retry apk add --no-cache build-base git \
    && retry pip --no-cache-dir --disable-pip-version-check install -e /src/orion-decision \
    && apk del build-base \
    && python3 -m compileall -b -q /usr/local/lib \
    && find /usr/local/lib -name \*.py -delete \
    && find /usr/local/lib -name __pycache__ -exec rm -rf \{\} + \
    && tar xf /tmp/pylibs-orig.tar \
    && find /usr/local/lib -name \*.py | while read f; do if [ -e "${f}c" ]; then echo "${f}c"; fi; done | xargs rm -f \
    && rm /tmp/pylibs-orig.tar

CMD ["decision"]
