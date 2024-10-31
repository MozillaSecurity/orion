# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM ubuntu:22.04

LABEL maintainer Christian Holler <choller@mozilla.com>

ENV LOGNAME         ubuntu
ENV HOSTNAME        taskcluster-worker
ARG DEBIAN_FRONTEND=noninteractive

RUN useradd -d /home/ubuntu -s /bin/bash -m ubuntu

COPY recipes/linux /src/recipes
COPY services/js-tests-distiller/setup.sh /src/recipes/setup-js-tests-distiller.sh
COPY services/js-tests-distiller/launch.sh /home/ubuntu/
RUN /src/recipes/setup-js-tests-distiller.sh

ENV LANG   en_US.UTF-8
ENV LC_ALL en_US.UTF-8

WORKDIR /home/ubuntu
USER ubuntu
CMD ["/home/ubuntu/launch.sh"]
