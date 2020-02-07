# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM python:3.8-slim

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

COPY pip.conf /etc/pip.conf

WORKDIR /root

RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="${i+1}"; done; "$@"; } \
    && retry apt-get update -qq \
    && retry apt-get install -y -qq --no-install-recommends --no-install-suggests \
        bzip2 \
        curl \
        git \
        jshon \
        libc6-dev \
        make \
        mercurial \
        openssh-client \
        patch \
        xz-utils \
    && retry pip -q install tox \
    && mkdir .ssh \
    && retry ssh-keyscan github.com > .ssh/known_hosts \
    && rm -rf /var/lib/apt/lists/*
