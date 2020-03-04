# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

ARG IMAGE=mozillasecurity/fuzzos:latest
# hadolint ignore=DL3006
FROM $IMAGE

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

USER root
RUN \
  apt-get update -qq \
  && apt-get install -y -qq --no-install-recommends --no-install-suggests \
    firefox \
    libpulse0 \
    subversion \
    screen \
  && "$HOME/.local/bin/cleanup.sh"

COPY *.sh ./
RUN chown -R worker:worker $HOME
USER $USER

CMD ["./setup.sh"]
