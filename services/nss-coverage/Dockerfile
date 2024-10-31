# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM ubuntu:22.04

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

ENV LOGNAME         worker
ENV HOSTNAME        taskcluster-worker
ARG DEBIAN_FRONTEND=noninteractive

RUN useradd -d /home/worker -s /bin/bash -m worker

COPY recipes/linux/ /src/recipes/
COPY services/fuzzing-decision /src/fuzzing-tc
COPY services/nss-coverage/setup.sh /src/recipes/setup-nss-coverage.sh
COPY \
    services/nss-coverage/libfuzzer-options.py \
    services/nss-coverage/merge-coverage.py \
    services/nss-coverage/nspr_map.json \
    services/nss-coverage/launch-worker.sh \
    services/nss-coverage/launch-root.sh \
    /home/worker/
RUN /src/recipes/setup-nss-coverage.sh

ENV LANG   en_US.UTF-8
ENV LC_ALL en_US.UTF-8

WORKDIR /home/worker
ENTRYPOINT ["/usr/local/bin/fuzzing-pool-launch"]
CMD ["/home/worker/launch-root.sh"]
