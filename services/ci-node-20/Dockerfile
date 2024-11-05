# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM node:20-slim

LABEL maintainer Jason Kratzer <jkratzer@mozilla.com>

COPY base/linux/etc/pip.conf /etc/pip.conf
COPY recipes/linux /src/recipes
COPY services/ci-node-common/setup-linux.sh /src/recipes/setup.sh
COPY services/orion-decision /src/orion-decision

RUN /src/recipes/setup.sh

USER worker
WORKDIR /home/worker
