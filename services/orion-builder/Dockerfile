# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM alpine:3.23

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

COPY services/orion-builder /src/orion-builder

RUN retry () { i=0; while [ $i -lt 9 ]; do if "$@"; then return; else sleep 30; fi; i="$((i+1))"; done; "$@"; } \
    && retry apk add --no-cache \
        # base packages
        cni-plugins \
        fuse-overlayfs \
        git \
        podman \
        skopeo \
        # orion-builder deps
        build-base \
        py3-pip \
        py3-requests \
        py3-wheel \
        python3 \
        python3-dev \
        zstd \
    && find /usr/lib/python3.* -type f -name EXTERNALLY-MANAGED -delete \
    && pip freeze > /src/os_constraints.txt \
    # configure podman
    && sed -i 's/^#mount_program/mount_program/' /etc/containers/storage.conf \
    # install task-boot
    && retry pip install --constraint /src/os_constraints.txt --disable-pip-version-check --no-cache-dir --progress-bar off git+https://github.com/mozilla/task-boot \
    # install orion-builder
    && retry pip install --constraint /src/os_constraints.txt --disable-pip-version-check --no-cache-dir --progress-bar off -e /src/orion-builder \
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
