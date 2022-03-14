# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM node:14-slim

LABEL maintainer Jason Kratzer <jkratzer@mozilla.com>

ARG DEBIAN_FRONTEND=noninteractive
ARG PYTHON_VER=3.9.10

COPY services/orion-decision /src/orion-decision
RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="${i+1}"; done; "$@"; } \
    && retry apt-get update -qq \
    && retry apt-get install -y -qq --no-install-recommends --no-install-suggests \
        ca-certificates \
        curl \
        git \
        jshon \
        locales \
        openssh-client \
    && savedAptMark="$(apt-mark showmanual)" \
    && retry apt-get install -y -qq --no-install-recommends --no-install-suggests \
        dpkg-dev \
        gcc \
        gnupg dirmngr \
        libbz2-dev \
        libc6-dev \
        libexpat1-dev \
        libffi-dev \
        libgdbm-dev \
        liblzma-dev \
        libncursesw5-dev \
        libreadline-dev \
        libsqlite3-dev \
        libssl-dev \
        make \
        uuid-dev \
        wget \
        xz-utils \
        zlib1g-dev \
    && retry curl -LO https://www.python.org/ftp/python/${PYTHON_VER}/Python-${PYTHON_VER}.tgz \
    && tar xzf Python-${PYTHON_VER}.tgz \
    && rm Python-${PYTHON_VER}.tgz \
    && cd Python-${PYTHON_VER} \
    && ./configure \
        --enable-optimizations \
        --enable-loadable-sqlite-extensions \
        --enable-optimizations \
        --enable-option-checking=fatal \
        --enable-shared \
        --with-system-expat \
        --with-system-ffi \
        --without-ensurepip \
    && make -j "$(nproc)" LDFLAGS="-Wl,--strip-all" \
    && make install \
    && cd .. \
    && rm -rf "Python-${PYTHON_VER}" \
    && rm -rf /usr/local/include/python* \
    && find /usr/local/lib/python* -depth \
        \( \
            \( -type d -a \( -name test -o -name tests -o -name idle_test \) \) \
            -o \( -type f -a \( -name '*.pyc' -o -name '*.pyo' -o -name '*.a' \) \) \
        \) -exec rm -rf '{}' + \
    && ldconfig \
    && apt-mark auto '.*' > /dev/null \
    && for p in $savedAptMark; do apt-mark manual "$p"; done \
    && find /usr/local -type f -executable -not \( -name '*tkinter*' \) -exec ldd '{}' ';' \
        | awk '/=>/ { print $(NF-1) }' \
        | sort -u \
        | xargs -r dpkg-query --search \
        | cut -d: -f1 \
        | sort -u \
        | xargs -r apt-mark manual \
    && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
    && rm -rf /var/lib/apt/lists/* \
    && retry curl -LO https://github.com/pypa/get-pip/raw/38e54e5de07c66e875c11a1ebbdb938854625dd8/public/get-pip.py \
    && export PYTHONDONTWRITEBYTECODE=1 \
    && python3 get-pip.py \
        --disable-pip-version-check \
        --no-cache-dir \
        --no-compile \
    && retry pip install --no-build-isolation -e /src/orion-decision \
    && useradd -d /home/worker -s /bin/bash -m worker \
    && echo "LANGUAGE=en" >> /etc/environment \
    && echo "LANG=en_US.UTF-8" >> /etc/environment \
    && echo "LC_ALL=en_US.UTF-8" >> /etc/environment \
    && sed -i 's/# en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen \
    && echo "LANG=en_US.UTF-8" > /etc/locale.conf \
    && locale-gen en_US.UTF-8 \
    && npm install -g npm@7

USER worker
WORKDIR /home/worker

RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="${i+1}"; done; "$@"; } \
    && mkdir .ssh \
    && retry ssh-keyscan github.com > .ssh/known_hosts
