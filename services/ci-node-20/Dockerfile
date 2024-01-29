# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM node:20-slim

LABEL maintainer Jason Kratzer <jkratzer@mozilla.com>

ARG DEBIAN_FRONTEND=noninteractive

COPY services/orion-decision /src/orion-decision
RUN retry () { i=0; while [ "$i" -lt 9 ]; do "$@" && return || sleep 30; i="${i+1}"; done; "$@"; } \
    && retry apt-get update -qq \
    && retry apt-get install -y -qq --no-install-recommends --no-install-suggests \
        ca-certificates \
        curl \
        git \
        jshon \
        locales \
        openssh-client \
        python3 \
        python3-setuptools \
    && savedAptMark="$(apt-mark showmanual)" \
    && retry apt-get install -y -qq --no-install-recommends --no-install-suggests \
        gcc \
        python3-dev \
        python3-pip \
        python3-venv \
        python3-wheel \
    && python3 -m venv /opt/orion-decision \
    && existVenv="$(ls /opt/orion-decision/bin)" \
    && retry /opt/orion-decision/bin/pip install /src/orion-decision \
    && apt-mark auto '.*' > /dev/null \
    && for p in $savedAptMark; do apt-mark manual "$p"; done \
    && venvInstalled="$(echo "$existVenv" "$(ls /opt/orion-decision/bin)" | tr ' ' '\n' | sort | uniq -u)" \
    && for b in $venvInstalled; do mv "/opt/orion-decision/bin/$b" /usr/local/bin; done \
    && find /usr/local -type f -executable -not \( -name '*tkinter*' \) -exec ldd '{}' ';' \
        | awk '/=>/ { print $(NF-1) }' \
        | sort -u \
        | xargs -r dpkg-query --search \
        | cut -d: -f1 \
        | sort -u \
        | xargs -r apt-mark manual \
    && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -d /home/worker -s /bin/bash -m worker \
    && echo "LANGUAGE=en" >> /etc/environment \
    && echo "LANG=en_US.UTF-8" >> /etc/environment \
    && echo "LC_ALL=en_US.UTF-8" >> /etc/environment \
    && sed -i 's/# en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen \
    && echo "LANG=en_US.UTF-8" > /etc/locale.conf \
    && locale-gen en_US.UTF-8

USER worker
WORKDIR /home/worker

RUN retry () { i=0; while [ "$i" -lt 9 ]; do "$@" && return || sleep 30; i="${i+1}"; done; "$@"; } \
    && mkdir .ssh \
    && retry ssh-keyscan github.com > .ssh/known_hosts
