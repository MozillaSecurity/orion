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

COPY \
    recipes/linux/cleanup.sh \
    recipes/linux/common.sh \
    recipes/linux/fluentbit.sh \
    recipes/linux/fuzzfetch.sh \
    recipes/linux/fuzzing_tc.sh \
    recipes/linux/fuzzmanager.sh \
    recipes/linux/grcov.sh \
    recipes/linux/js32_deps.sh \
    recipes/linux/llvm.sh \
    recipes/linux/llvm-cov.sh \
    recipes/linux/llvm-symbolizer.sh \
    recipes/linux/sentry.sh \
    recipes/linux/taskcluster.sh \
    recipes/linux/taskgraph-m-c-latest.sh \
    services/fuzzilli/setup.sh \
    /srv/repos/setup/
COPY services/fuzzing-decision /srv/repos/fuzzing-decision

RUN /srv/repos/setup/setup.sh
COPY services/fuzzilli/coverage.sh \
     services/fuzzilli/fuzzilli.sh \
     services/fuzzilli/launch.sh \
     /home/ubuntu/
COPY services/fuzzilli/fluentbit.conf /etc/td-agent-bit/td-agent-bit.conf
COPY services/fuzzilli/sysctl.conf /etc/sysctl.d/60-fuzzilli.conf

ENV LANG   en_US.UTF-8
ENV LC_ALL en_US.UTF-8

WORKDIR /home/ubuntu
ENTRYPOINT ["/usr/local/bin/fuzzing-pool-launch"]
CMD ["/home/ubuntu/launch.sh"]
