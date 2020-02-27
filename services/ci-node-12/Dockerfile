# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM node:12-slim

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

ENV DEBIAN_FRONTEND noninteractive

RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="${i+1}"; done; "$@"; } \
    && retry apt-get update -qq \
    && retry apt-get install -y -qq --no-install-recommends --no-install-suggests \
        ca-certificates \
        curl \
        git \
        jshon \
        locales \
        openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -d /home/worker -s /bin/bash -m worker \
    && echo -e "LANGUAGE=en\nLANG=en_US.UTF-8\nLC_ALL=en_US.UTF-8" >> /etc/environment \
    && sed -i 's/# en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen \
    && echo "LANG=en_US.UTF-8" > /etc/locale.conf \
    && locale-gen en_US.UTF-8

USER worker
WORKDIR /home/worker

RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="${i+1}"; done; "$@"; } \
    && mkdir .ssh \
    && retry ssh-keyscan github.com > .ssh/known_hosts
