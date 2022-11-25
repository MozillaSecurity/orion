# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM alpine:latest

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

ARG REGISTRY_VER="2.8.1"
ARG REGISTRY_REV="0be0d08b29d56bb1ef0fab93c751ca92d6976a19"
ARG IMG_VER="16d3b6cad7e72f4cd9c8dad0e159902eeee00898"
ARG FUSE_OVERLAYFS_VER="refs/tags/v1.9"
ARG TASKBOOT_VER="0.3.5"

COPY services/orion-builder /src/orion-builder
RUN retry () { i=0; while [ $i -lt 9 ]; do if "$@"; then return; else sleep 30; fi; i="$((i+1))"; done; "$@"; } \
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
    && retry git fetch -q --depth 1 --no-tags origin "$FUSE_OVERLAYFS_VER:$FUSE_OVERLAYFS_VER" \
    && git -c advice.detachedHead=false checkout "$FUSE_OVERLAYFS_VER" \
    && ./autogen.sh \
    && ./configure --prefix /usr \
    && make clean \
    && make \
    && make install \
    && cd / \
    && rm -rf /usr/share/man/man1 /fuse-overlayfs \
    # build img with fuse-overlayfs backend
    && git init /img \
    && cd /img \
    && git remote add origin https://github.com/genuinetools/img \
    && retry git fetch -q --depth 1 --no-tags origin "$IMG_VER" \
    && git -c advice.detachedHead=false checkout "$IMG_VER" \
    && retry go get -u github.com/jteeuwen/go-bindata/... \
    && retry make BUILDTAGS="seccomp noembed" \
    && strip img \
    && mv img /usr/bin \
    && cd / \
    && rm -rf /img /root/.cache /root/go \
    # install orion-builder
    && retry pip --no-cache-dir --disable-pip-version-check install "https://github.com/mozilla/task-boot/archive/$TASKBOOT_VER.tar.gz" \
    && retry pip --no-cache-dir --disable-pip-version-check install -e /src/orion-builder \
    && find /usr/lib/python*/site-packages -name "*.so" -exec strip "{}" + \
    && rm -rf /root/.cache /usr/bin/__pycache__ \
    # precompile .py files
    && python -m compileall -b -q /usr/lib \
    && find /usr/lib -name \*.py -delete \
    && find /usr/lib -name __pycache__ -exec rm -rf "{}" + \
    # install docker registry
    && retry wget -q -O registry.tar.gz "https://github.com/distribution/distribution/releases/download/v$REGISTRY_VER/registry_${REGISTRY_VER}_linux_amd64.tar.gz" \
    && tar --extract --verbose --file registry.tar.gz --directory /bin/ registry \
    && rm registry.tar.gz \
    && retry wget -q -O /root/registry.yml https://github.com/docker/distribution-library-image/raw/$REGISTRY_REV/config-example.yml \
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
