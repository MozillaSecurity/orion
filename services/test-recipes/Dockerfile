# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM ubuntu:22.04

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

ARG DEBIAN_FRONTEND=noninteractive
ARG recipe

COPY recipes/linux /recipes
COPY services/test-recipes/launch.sh /

RUN chmod +x /launch.sh && exec /launch.sh
