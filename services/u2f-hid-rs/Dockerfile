# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM mozillasecurity/fuzzos:latest

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

COPY setup.sh .

USER root
RUN \
  apt-get update -qq \
  && apt-get install -y -qq --no-install-recommends --no-install-suggests \
    subversion \
    gcc \
    libudev-dev \
    pkg-config \
  && apt-get clean -y \
  && apt-get autoclean -y \
  && apt-get autoremove -y \
  && rm -rf /var/lib/apt/lists/* \
  && rm -rf /root/.cache/* \
  && chown -R worker:worker /home/worker

ENTRYPOINT ["./setup.sh"]
