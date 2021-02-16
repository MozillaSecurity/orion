# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM alpine:latest

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

ARG REGISTRY_VER="b804bcd6a44de56fcf8ff3f0ababae7479ad608e"
ARG IMG_VER="3667c6a05b1a2c2c6b680e2323fbcc9ed76947a8"
ARG FUSE_OVERLAYFS_VER="refs/tags/v1.4.0"

COPY services/orion-builder /src/orion-builder
RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="$((i+1))"; done; "$@"; } \
    && retry apk add --no-cache \
        # base packages
        git \
        openssl \
        skopeo \
        # fuse-overlayfs deps
        autoconf \
        automake \
        build-base \
        fuse3 \
        fuse3-dev \
        linux-headers \
        # img deps
        bash \
        build-base \
        go \
        libseccomp-dev \
        pigz \
        runc \
        shadow-uidmap \
        # orion-builder deps
        build-base \
        py3-pip \
        py3-requests \
        py3-wheel \
        python3 \
        python3-dev \
    # build fuse-overlayfs
    && git init /fuse-overlayfs \
    && cd /fuse-overlayfs \
    && git remote add origin https://github.com/containers/fuse-overlayfs \
    && retry git fetch -q origin "$FUSE_OVERLAYFS_VER:$FUSE_OVERLAYFS_VER" \
    && git -c advice.detachedHead=false checkout "$FUSE_OVERLAYFS_VER" \
    && ./autogen.sh \
    && ./configure --prefix /usr || cat config.log \
    && make clean \
    && make \
    && make install \
    && cd / \
    && rm -rf /usr/share/man/man1 /fuse-overlayfs \
    # build img with fuse-overlayfs backend
    && git init /img \
    && cd /img \
    && git remote add origin https://github.com/genuinetools/img \
    && retry git fetch -q origin "$IMG_VER" \
    && git -c advice.detachedHead=false checkout "$IMG_VER" \
    && retry go get -u github.com/jteeuwen/go-bindata/... \
    && retry make BUILDTAGS="seccomp noembed" \
    && strip img \
    && mv img /usr/bin \
    && cd / \
    && rm -rf /img /root/.cache /root/go \
    # install orion-builder
    && ln -s /usr/bin/python3 /usr/bin/python \
    && retry pip --no-cache-dir --disable-pip-version-check install https://github.com/mozilla/task-boot/archive/0.3.2.tar.gz \
    && retry pip --no-cache-dir --disable-pip-version-check install -e /src/orion-builder \
    && find /usr/lib/python*/site-packages -name "*.so" -exec strip {} \; \
    && rm -rf /root/.cache /usr/bin/__pycache__ \
    # precompile .py files
    && python -m compileall -b -q /usr/lib \
    && find /usr/lib -name \*.py -delete \
    && find /usr/lib -name __pycache__ -exec rm -rf \{\} + \
    # install docker registry
    && retry wget -q -O /bin/registry https://github.com/docker/distribution-library-image/raw/$REGISTRY_VER/amd64/registry \
    && retry wget -q -O /root/registry.yml https://github.com/docker/distribution-library-image/raw/$REGISTRY_VER/amd64/config-example.yml \
    && chmod +x /bin/registry \
    # cleanup
    && apk del \
        autoconf \
        automake \
        bash \
        build-base \
        fuse3-dev \
        go \
        libseccomp-dev \
        linux-headers \
        py3-pip \
        py3-wheel \
        python3-dev
