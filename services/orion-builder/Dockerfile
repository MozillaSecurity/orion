# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM alpine:edge

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

ARG REGISTRY_VER="b804bcd6a44de56fcf8ff3f0ababae7479ad608e"

COPY services/orion-builder /src/orion-builder
RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="$((i+1))"; done; "$@"; } \
    && retry apk add --no-cache --quiet build-base git img openssl python3 skopeo \
    && ln -s /usr/bin/python3 /usr/bin/python \
    && retry python -m ensurepip \
    && retry python -m pip --no-cache-dir --disable-pip-version-check install --upgrade pip setuptools wheel \
    && retry pip --no-cache-dir --disable-pip-version-check install https://github.com/mozilla/task-boot/archive/0.2.7.tar.gz \
    && pip --no-cache-dir --disable-pip-version-check install -e /src/orion-builder \
    && apk del build-base \
    && python -m compileall -b -q /usr/lib \
    && find /usr/lib -name \*.py -delete \
    && find /usr/lib -name __pycache__ -exec rm -rf \{\} + \
    && retry wget -q -O /bin/registry https://github.com/docker/distribution-library-image/raw/$REGISTRY_VER/amd64/registry \
    && retry wget -q -O /root/registry.yml https://github.com/docker/distribution-library-image/raw/$REGISTRY_VER/amd64/config-example.yml \
    && chmod +x /bin/registry
