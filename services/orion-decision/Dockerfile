# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM alpine:latest

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

COPY services/orion-decision /src/orion-decision

RUN retry () { i=0; while [ $i -lt 9 ]; do if "$@"; then return; else sleep 30; fi; i="$((i+1))"; done; "$@"; } \
    && retry apk add --no-cache \
        build-base \
        git \
        openssh-client \
        py3-pip \
        py3-requests \
        py3-setuptools \
        py3-six \
        py3-wheel \
        py3-yaml \
        python3 \
        python3-dev \
    && find /usr/lib/python3.* -type f -name EXTERNALLY-MANAGED -delete \
    && pip freeze > /src/os_constraints.txt \
    && retry pip install --constraint /src/os_constraints.txt --disable-pip-version-check --no-cache-dir --progress-bar off -e /src/orion-decision \
    && find /usr/lib/python*/site-packages -name "*.so" -exec strip {} \; \
    && apk del build-base py3-pip py3-wheel python3-dev \
    && python -m compileall -b -q /usr/lib \
    && find /usr/lib -name \*.py -delete \
    && find /usr/lib -name __pycache__ -exec rm -rf \{\} + \
    && mkdir -p /root/.ssh \
    && retry ssh-keyscan github.com > /root/.ssh/known_hosts

CMD ["decision"]
