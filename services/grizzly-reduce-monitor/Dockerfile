# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM alpine:latest

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

COPY services/grizzly-reduce-monitor /src

RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="${i+1}"; done; "$@"; } \
    && retry apk add --no-cache \
        git \
        python3 \
        py3-aiohttp \
        py3-multidict \
        py3-pip \
        py3-psutil \
        py3-requests \
        py3-six \
        py3-wheel \
        py3-yarl \
    && pip freeze > /src/os_constraints.txt \
    && retry pip install --constraint /src/os_constraints.txt --disable-pip-version-check --no-cache-dir --progress-bar off -e /src \
    && apk del git py3-pip py3-wheel \
    && python3 -m compileall -b -q /usr/lib \
    && find /usr/lib -name "*.py" -delete \
    && find /usr/lib -name __pycache__ -exec rm -rf \{\} +

ENTRYPOINT ["/usr/bin/grizzly-reduce-tc-log-private"]
