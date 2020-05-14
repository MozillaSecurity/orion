# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM ubuntu:18.04

LABEL maintainer Christian Holler <choller@mozilla.com>

ENV LOGNAME         ubuntu
ENV HOSTNAME        taskcluster-worker
ENV DEBIAN_FRONTEND noninteractive

RUN useradd -d /home/ubuntu -s /bin/bash -m ubuntu

COPY services/langfuzz/setup.sh /tmp/
RUN /tmp/setup.sh \
    && rm -rf /tmp/setup.sh
COPY services/langfuzz/launch-langfuzz.sh /home/ubuntu/

ENV LANG   en_US.UTF-8
ENV LC_ALL en_US.UTF-8

WORKDIR /home/ubuntu
ENTRYPOINT ["/usr/local/bin/fuzzing-pool-launch"]
CMD ["/home/ubuntu/launch-langfuzz.sh"]
