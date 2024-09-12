# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM python:3.12-slim

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

COPY services/failed-task-ingestor /src

RUN retry () { i=0; while [ $i -lt 9 ]; do if "$@"; then return; else sleep 30; fi; i="$((i+1))"; done; "$@"; } \
    && retry pip install /src

CMD ["ingest"]
