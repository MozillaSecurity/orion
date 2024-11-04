# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM ubuntu:22.04

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

COPY recipes/linux/ /tmp/recipes/
COPY services/libfuzzer/setup.sh /tmp/recipes/
COPY services/fuzzing-decision /tmp/fuzzing-tc
COPY base/linux/etc/pip.conf /etc/pip.conf
RUN /tmp/recipes/setup.sh \
  && rm -rf /tmp/recipes /tmp/fuzzing-tc

COPY services/libfuzzer/launch.sh \
  services/libfuzzer/libfuzzer.sh \
  services/libfuzzer/coverage.sh \
  services/libfuzzer/setup-target.sh \
  /home/worker/

WORKDIR /home/worker
ENTRYPOINT ["/usr/local/bin/fuzzing-pool-launch"]
CMD ["./launch.sh"]
