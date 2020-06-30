# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM ubuntu:18.04

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

ENV LOGNAME         worker
ENV HOSTNAME        taskcluster-worker
ENV DEBIAN_FRONTEND noninteractive

RUN useradd -d /home/worker -s /bin/bash -m worker

COPY recipes/linux/ /tmp/recipes/
COPY services/libfuzzer/setup.sh /tmp/recipes/
COPY base/linux/etc/pip.conf /etc/pip.conf
RUN /tmp/recipes/setup.sh \
    && rm -rf /tmp/recipes

COPY services/libfuzzer/launch.sh /home/worker/
COPY services/libfuzzer/libfuzzer.sh /home/worker/
COPY services/libfuzzer/coverage.sh /home/worker/
COPY services/libfuzzer/setup-target.sh /home/worker/

ENV LANG   en_US.UTF-8
ENV LC_ALL en_US.UTF-8

WORKDIR /home/worker
ENTRYPOINT ["/usr/local/bin/fuzzing-pool-launch"]
CMD ["./launch.sh"]
