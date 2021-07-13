# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM node:10-alpine

LABEL maintainer Jason Kratzer <jkratzer@mozilla.com>

COPY services/orion-decision /src/orion-decision

ENV LANGUAGE en
ENV LANG en_US.UTF-8
ENV LC_ALL en_US.UTF-8

RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="$((i+1))"; done; "$@"; } \
    && adduser -D worker \
    && retry apk add --no-cache curl git libintl openssh-client python3 py3-yarl \
    && ln -s /usr/bin/python3 /usr/bin/python \
    && retry apk --no-cache --virtual .locale_build add cmake make musl-dev gcc gettext-dev \
    && git clone https://gitlab.com/rilian-la-te/musl-locales \
    && cd musl-locales && cmake -DLOCALE_PROFILE=OFF -DCMAKE_INSTALL_PREFIX:PATH=/usr . && make && make install \
    && cd .. && rm -r musl-locales \
    && apk del .locale_build \
    && retry python -m pip install --no-cache-dir --disable-pip-version-check --progress-bar off -e "/src/orion-decision" \
    && python -m compileall -b -q /usr/lib \
    && find /usr/lib -name \*.py -delete \
    && find /usr/lib -name __pycache__ -exec rm -rf "{}" + \
    && npm install -g npm@7 \
    && su worker -c "mkdir ~worker/.ssh" \
    && retry su worker -c "ssh-keyscan github.com > ~worker/.ssh/known_hosts"

USER worker
WORKDIR /home/worker
