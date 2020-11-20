# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM python:3.9-alpine

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

ARG IMG_VER="0.5.11"
ARG REGISTRY_VER="b804bcd6a44de56fcf8ff3f0ababae7479ad608e"

# install required runtime packages
RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="$((i+1))"; done; "$@"; } \
    && retry apk add --no-cache --quiet git openssl skopeo

# build img without `go` runtime dependency required by the apkg version
RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="$((i+1))"; done; "$@"; } \
    && retry apk add --no-cache --quiet bash build-base go libseccomp-dev runc shadow-uidmap \
    && git init /img \
    && cd /img \
    && git remote add origin https://github.com/genuinetools/img \
    && retry git fetch -q origin refs/tags/v$IMG_VER:refs/tags/v$IMG_VER \
    && git -c advice.detachedHead=false checkout v$IMG_VER \
    && GOPATH="$(pwd)" \
    && retry go get -u github.com/jteeuwen/go-bindata/... \
    && retry make BUILDTAGS="seccomp noembed" \
    && strip img \
    && mv img /usr/bin \
    && cd / \
    && rm -rf /img /root/go \
    && apk del bash build-base go libseccomp-dev

# install the docker distribution registry binary
RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="$((i+1))"; done; "$@"; } \
    && retry wget -q -O /bin/registry https://github.com/docker/distribution-library-image/raw/$REGISTRY_VER/amd64/registry \
    && retry wget -q -O /root/registry.yml https://github.com/docker/distribution-library-image/raw/$REGISTRY_VER/amd64/config-example.yml \
    && chmod +x /bin/registry

# install builder
COPY services/orion-builder /src/orion-builder
RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="$((i+1))"; done; "$@"; } \
    && retry apk add --no-cache --quiet build-base \
    && tar cf /tmp/pylibs-orig.tar /usr/local/lib \
    && retry pip --no-cache-dir --disable-pip-version-check install https://github.com/mozilla/task-boot/archive/0.2.7.tar.gz \
    && pip --no-cache-dir --disable-pip-version-check install -e /src/orion-builder \
    && apk del build-base \
    && python3 -m compileall -b -q /usr/local/lib \
    && find /usr/local/lib -name \*.py -delete \
    && find /usr/local/lib -name __pycache__ -exec rm -rf \{\} + \
    && tar xf /tmp/pylibs-orig.tar \
    && find /usr/local/lib -name \*.py | while read f; do if [ -e "${f}c" ]; then echo "${f}c"; fi; done | xargs rm -f \
    && rm /tmp/pylibs-orig.tar
