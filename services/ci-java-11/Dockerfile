# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM debian:stable-slim

LABEL maintainer Jesse Schwartzentruber <jschwartzentruber@mozilla.com>

COPY recipes/linux /src/recipes
COPY services/ci-java-11/setup.sh /src/recipes/setup.sh
COPY services/orion-decision /src/orion-decision

RUN /src/recipes/setup.sh

USER worker
WORKDIR /home/worker
