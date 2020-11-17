# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM python:3.9-alpine

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

COPY services/orion-decision /tmp/orion-decision
RUN retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="${i+1}"; done; "$@"; } \
    && retry apk add --no-cache gcc musl-dev \
    && retry pip install /tmp/orion-decision \
    && apk del gcc musl-dev \
    && rm -rf /tmp/orion-decision

CMD ["decision"]
