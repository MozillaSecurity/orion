# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM alpine:latest AS builder

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

RUN function retry () { for _ in {1..9}; do "$@" && return || sleep 30; done; "$@"; } \
    && retry apk --no-cache add \
        build-base \
        libressl-dev \
        libffi-dev \
        python3 \
        python3-dev \
    && retry python3 -m pip install --upgrade pip wheel \
    && retry python3 -m pip wheel --wheel-dir=/root/wheels credstash

FROM alpine:latest

COPY --from=builder /root/wheels /root/wheels

RUN function retry () { for _ in {1..9}; do "$@" && return || sleep 30; done; "$@"; } \
    && retry apk add --no-cache python3 libressl \
    && python3 -m pip install --no-index --find-links=/root/wheels credstash \
    && rm -rf /root/wheels \
    && python3 -m compileall -b -q /usr/lib \
    && find /usr/lib -name \*.py -delete \
    && find /usr/lib -name __pycache__ -exec rm -rf \{\} +

ENTRYPOINT ["python3", "-m", "credstash"]
