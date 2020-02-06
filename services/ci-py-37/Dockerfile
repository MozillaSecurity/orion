# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM python:3.7-slim

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

ADD pip.conf /etc/pip.conf

WORKDIR /root

RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends --no-install-suggests \
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
    && pip -q install tox \
    && mkdir .ssh \
    && ssh-keyscan github.com > .ssh/known_hosts \
    && git init repo \
    && cd repo \
    && git config advice.detachedHead false \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /root/repo

ENTRYPOINT ["/bin/bash"]
