# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM mozilla/taskboot:0.2.7

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

ARG REGISTRY_REV=b804bcd6a44de56fcf8ff3f0ababae7479ad608e

RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="${i+1}"; done; "$@"; } \
    && retry apk add --no-cache --quiet ca-certificates openssl \
    && retry wget -q -O /bin/registry https://github.com/docker/distribution-library-image/raw/$REGISTRY_REV/amd64/registry \
    && retry wget -q -O /root/registry.yml https://github.com/docker/distribution-library-image/raw/$REGISTRY_REV/amd64/config-example.yml \
    && chmod +x /bin/registry

COPY services/taskboot/build.sh /usr/local/bin/build.sh
