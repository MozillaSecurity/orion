# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM alpine:latest

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

COPY services/fuzzing-decision /src/fuzzing-decision
RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="$((i+1))"; done; "$@"; } \
    && retry apk add --no-cache build-base git openssh-client python3 py3-pip py3-requests py3-wheel python3-dev \
    && ln -s /usr/bin/python3 /usr/bin/python \
    && retry pip install --no-cache-dir --disable-pip-version-check --progress-bar off -e "/src/fuzzing-decision[decision]" \
    && find /usr/lib/python*/site-packages -name "*.so" -exec strip "{}" + \
    && apk del build-base py3-pip py3-wheel python3-dev \
    && python -m compileall -b -q /usr/lib \
    && find /usr/lib -name \*.py -delete \
    && find /usr/lib -name __pycache__ -exec rm -rf "{}" + \
    && mkdir -p ~/.ssh \
    && chmod 0700 ~/.ssh \
    && ssh-keyscan github.com > ~/.ssh/known_hosts

# Setup env variable for tc-admin.py discovery
ENV TC_ADMIN_PY=/src/fuzzing-decision/tc-admin.py

CMD ["fuzzing-decision"]
