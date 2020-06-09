# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM alpine:latest

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="${i+1}"; done; "$@"; } \
    && retry apk add --no-cache \
        py3-cryptography \
        py3-pip \
        py3-six \
        py3-urllib3 \
        py3-wheel \
        python3 \
    && retry python3 -m pip install credstash \
    && apk del py3-pip py3-wheel \
    && python3 -m compileall -b -q /usr/lib \
    && find /usr/lib -name \*.py -delete \
    && find /usr/lib -name __pycache__ -exec rm -rf \{\} +

ENTRYPOINT ["python3", "-m", "credstash"]
