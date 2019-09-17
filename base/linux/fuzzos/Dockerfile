# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

#FROM ubuntu:18.04
ARG IMAGE=mozillasecurity/core
FROM $IMAGE

LABEL maintainer Christoph Diehl <cdiehl@mozilla.com>

ENV USER            worker
ENV HOME            /home/worker
ENV LOGNAME         worker
ENV HOSTNAME        taskcluster-worker
ENV CC              clang
ENV CXX             clang++
ENV DEBIAN_FRONTEND noninteractive

RUN useradd -d $HOME -s /bin/bash -m $USER
WORKDIR $HOME

COPY setup.sh /tmp
COPY recipes /tmp/recipes

RUN cd /tmp && ./setup.sh

ENV LANG   en_US.UTF-8
ENV LC_ALL en_US.UTF-8

RUN chown -R worker:worker $HOME
USER $USER

CMD ["/bin/bash", "--login"]
