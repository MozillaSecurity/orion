# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM ubuntu:22.04

LABEL maintainer Christian Holler <choller@mozilla.com>

ENV LOGNAME         ubuntu
ENV HOSTNAME        taskcluster-worker
ARG DEBIAN_FRONTEND=noninteractive
ENV TASKCLUSTER_FUZZING_POOL unknown

RUN useradd -d /home/ubuntu -s /bin/bash -m ubuntu

COPY recipes/linux /src/recipes
COPY services/fuzzing-decision /src/fuzzing-tc
COPY services/fuzzilli/setup.sh /src/recipes/setup-fuzzilli.sh
RUN /src/recipes/setup-fuzzilli.sh
COPY services/fuzzilli/launch.sh /home/ubuntu/
COPY services/fuzzilli/fuzzilli.sh /home/ubuntu/
COPY services/fuzzilli/fluentbit.conf /etc/td-agent-bit/td-agent-bit.conf
COPY services/fuzzilli/sysctl.conf /etc/sysctl.d/60-fuzzilli.conf

ENV LANG   en_US.UTF-8
ENV LC_ALL en_US.UTF-8

WORKDIR /home/ubuntu
ENTRYPOINT ["/usr/local/bin/fuzzing-pool-launch"]
CMD ["/home/ubuntu/launch.sh"]
