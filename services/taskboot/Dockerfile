# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM mozilla/taskboot:0.2.7

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="$((i+1))"; done; "$@"; } \
    && retry apk add --no-cache --quiet jq openssl \
    && retry wget -q -O /bin/registry https://github.com/docker/distribution-library-image/raw/b804bcd6a44de56fcf8ff3f0ababae7479ad608e/amd64/registry \
    && retry wget -q -O /root/registry.yml https://github.com/docker/distribution-library-image/raw/b804bcd6a44de56fcf8ff3f0ababae7479ad608e/amd64/config-example.yml \
    && retry wget -q -O /bin/taskcluster https://github.com/taskcluster/taskcluster/releases/download/v38.0.6/taskcluster-linux-amd64 \
    && chmod +x /bin/registry /bin/taskcluster \
    && strip /bin/taskcluster \
    && mkdir /lib64 \
    && ln -s /lib/ld-musl-x86_64.so.1 /lib64/ld-linux-x86-64.so.2

ENV DOCKER_API_VERSION 1.18

COPY services/taskboot/build.sh /usr/local/bin/build
COPY services/taskboot/push.sh /usr/local/bin/push
COPY services/taskboot/stage_deps.sh /usr/local/bin/stage_deps
COPY services/taskboot/common.sh /usr/local/share/taskboot_common.sh
