# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM python:3.11-slim

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

COPY base/linux/etc/pip.conf /etc/pip.conf
COPY recipes/linux /src/recipes
COPY services/ci-py-common/setup-linux.sh /src/recipes/setup.sh
COPY services/orion-decision /src/orion-decision

ARG DEBIAN_FRONTEND=noninteractive

RUN /src/recipes/setup.sh

USER worker
WORKDIR /home/worker
