# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM ubuntu:20.04

LABEL maintainer Christian Holler <choller@mozilla.com>

ENV LOGNAME         ubuntu
ENV HOSTNAME        taskcluster-worker
ARG DEBIAN_FRONTEND=noninteractive
ENV TASKCLUSTER_FUZZING_POOL unknown

RUN useradd -d /home/ubuntu -s /bin/bash -m ubuntu

COPY services/fuzzing-decision /tmp/fuzzing-tc
COPY services/langfuzz/setup.sh /tmp/
RUN /tmp/setup.sh \
    && rm -rf /tmp/setup.sh /tmp/fuzzing-tc
COPY services/langfuzz/launch-langfuzz.sh /home/ubuntu/
COPY services/langfuzz/fluentbit.conf /etc/td-agent-bit/td-agent-bit.conf
COPY services/langfuzz/sysctl.conf /etc/sysctl.d/60-langfuzz.conf

ENV LANG   en_US.UTF-8
ENV LC_ALL en_US.UTF-8

WORKDIR /home/ubuntu
ENTRYPOINT ["/usr/local/bin/fuzzing-pool-launch"]
CMD ["/home/ubuntu/launch-langfuzz.sh"]
