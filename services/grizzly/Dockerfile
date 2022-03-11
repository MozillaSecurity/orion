# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM ubuntu:20.04

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

ENV LOGNAME         worker
ENV HOSTNAME        taskcluster-worker
ARG DEBIAN_FRONTEND=noninteractive

RUN useradd -d /home/worker -s /bin/bash -m worker

COPY recipes/linux/ /src/recipes/
COPY \
    services/grizzly/pyproject.toml \
    services/grizzly/rwait.py \
    services/grizzly/setup.cfg \
    services/grizzly/setup.py \
    /src/rwait/
COPY services/fuzzing-decision /src/fuzzing-tc
COPY services/grizzly/setup.sh /src/recipes/setup-grizzly.sh
COPY base/linux/etc/pip.conf /etc/pip.conf
RUN /src/recipes/setup-grizzly.sh
COPY services/grizzly/launch-grizzly.sh services/grizzly/launch-grizzly-worker.sh /home/worker/

ENV LANG   en_US.UTF-8
ENV LC_ALL en_US.UTF-8

WORKDIR /home/worker
ENTRYPOINT ["/usr/local/bin/fuzzing-pool-launch"]
CMD ["/home/worker/launch-grizzly.sh"]
