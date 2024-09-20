# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM ubuntu:24.04

LABEL maintainer="Maurice Dauer <mdauer@mozilla.com>"

ENV LOGNAME=worker
ENV HOSTNAME=taskcluster-worker
ARG DEBIAN_FRONTEND=noninteractive

RUN useradd -d /home/worker -s /bin/bash -m worker

COPY recipes/linux/ /src/recipes/
COPY services/nss-corpus-update/setup.sh /src/recipes/setup-nss-corpus-update.sh
COPY services/nss-corpus-update/ssh_config /home/worker/.ssh/config
COPY services/nss-corpus-update/launch.sh /home/worker/

RUN /src/recipes/setup-nss-corpus-update.sh

ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

USER worker
WORKDIR /home/worker
CMD ["/home/worker/launch.sh"]
