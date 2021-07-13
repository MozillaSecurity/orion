# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM node:16-alpine

LABEL maintainer Jason Kratzer <jkratzer@mozilla.com>

COPY services/orion-decision /src/orion-decision

ENV LANGUAGE en
ENV LANG en_US.UTF-8
ENV LC_ALL en_US.UTF-8

RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="$((i+1))"; done; "$@"; } \
    && adduser -D worker \
    && retry apk add --no-cache curl git musl-locales openssh-client python3 py3-pip py3-requests py3-wheel py3-yarl \
    && ln -s /usr/bin/python3 /usr/bin/python \
    && retry python -m pip install --no-cache-dir --disable-pip-version-check --progress-bar off -e "/src/orion-decision" \
    && python -m compileall -b -q /usr/lib \
    && find /usr/lib -name \*.py -delete \
    && find /usr/lib -name __pycache__ -exec rm -rf "{}" + \
    && apk del py3-pip py3-wheel \
    && su worker -c "mkdir ~worker/.ssh" \
    && retry su worker -c "ssh-keyscan github.com > ~worker/.ssh/known_hosts"

USER worker
WORKDIR /home/worker
