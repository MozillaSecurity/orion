# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM python:3.10-slim

LABEL maintainer Jason Kratzer <jkratzer@mozilla.com>

ENV LOGNAME         worker
ENV HOSTNAME        taskcluster-worker
ARG DEBIAN_FRONTEND=noninteractive

USER root
COPY base/linux/etc/pip.conf /etc/pip.conf
COPY recipes/linux/ /src/recipes/
RUN /src/recipes/python-worker.sh

WORKDIR /home/worker
COPY services/prefmonitor/setup.sh /src/recipes/setup-prefmonitor.sh
COPY services/prefmonitor/ssh_config /home/worker/.ssh/config
COPY services/prefmonitor/launch.sh /home/worker
RUN /src/recipes/setup-prefmonitor.sh

USER worker
WORKDIR /home/worker
ENTRYPOINT ["/usr/bin/env"]
CMD ["/home/worker/launch.sh"]
