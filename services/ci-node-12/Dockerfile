# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM node:12-slim

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

WORKDIR /root

RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="${i+1}"; done; "$@"; } \
    && retry apt-get update -qq \
    && retry apt-get install -y -qq --no-install-recommends --no-install-suggests \
        curl \
        git \
        jshon \
        openssh-client \
    && mkdir .ssh \
    && retry ssh-keyscan github.com > .ssh/known_hosts \
    && rm -rf /var/lib/apt/lists/*
