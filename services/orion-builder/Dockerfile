# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM alpine:latest

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

ARG TASKBOOT_VER="0.3.5"

COPY services/orion-builder /src/orion-builder
RUN retry () { i=0; while [ $i -lt 9 ]; do if "$@"; then return; else sleep 30; fi; i="$((i+1))"; done; "$@"; } \
    && retry apk add --no-cache \
        # base packages
        cni-plugins \
        git \
        podman \
        fuse-overlayfs \
        # orion-builder deps
        build-base \
        py3-pip \
        py3-requests \
        py3-wheel \
        python3 \
        python3-dev \
    # configure podman
    && sed -i 's/^#mount_program/mount_program/' /etc/containers/storage.conf \
    # install task-boot
    && retry wget -q https://github.com/mozilla/task-boot/archive/$TASKBOOT_VER.tar.gz \
    && tar xzf $TASKBOOT_VER.tar.gz \
    && cd task-boot-$TASKBOOT_VER \
    && patch -p1 -i /src/orion-builder/podman.patch \
    && retry pip --no-cache-dir --disable-pip-version-check install . \
    && cd .. \
    && rm -rf $TASKBOOT_VER.tar.gz task-boot-$TASKBOOT_VER \
    # install orion-builder
    && retry pip --no-cache-dir --disable-pip-version-check install -e /src/orion-builder \
    && find /usr/lib/python*/site-packages -name "*.so" -exec strip "{}" + \
    && rm -rf /root/.cache /usr/bin/__pycache__ \
    # precompile .py files
    && python -m compileall -b -q /usr/lib \
    && find /usr/lib -name \*.py -delete \
    && find /usr/lib -name __pycache__ -exec rm -rf "{}" + \
    # cleanup
    && apk del \
        build-base \
        py3-pip \
        py3-wheel \
        python3-dev
