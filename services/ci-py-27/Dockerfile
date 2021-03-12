# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM python:2.7-slim

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

COPY base/linux/etc/pip.conf /etc/pip.conf
COPY recipes/linux /src/recipes
COPY services/orion-decision /src/orion-decision

ARG DEBIAN_FRONTEND=noninteractive

# hadolint ignore=SC1091
RUN . /src/recipes/common.sh \
    && sys-update \
    && sys-embed \
        bzip2 \
        curl \
        gcc \
        git \
        jshon \
        libc6-dev \
        make \
        mercurial \
        openssh-client \
        patch \
        xz-utils \
    && retry pip -q install tox \
    && retry pip install poetry \
    && SRCDIR=/src/orion-decision EDIT=1 /src/recipes/orion_decision.sh \
    && /src/recipes/worker.sh \
    && /src/recipes/cleanup.sh

USER worker
WORKDIR /home/worker

# hadolint ignore=SC1091
RUN . /src/recipes/common.sh \
    && ln /src/recipes/py-ci.sh . \
    && mkdir .ssh \
    && retry ssh-keyscan github.com > .ssh/known_hosts
