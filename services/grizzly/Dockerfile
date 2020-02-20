# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM mozillasecurity/fuzzos:latest

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

USER root
COPY recipes/ /tmp/recipes/
RUN /tmp/recipes/setup.sh \
    && rm -rf /tmp/recipes
COPY screenlog-to-cloudwatch.py /usr/local/bin/
COPY launch-grizzly.sh /home/worker/
COPY launch-grizzly-worker.sh /home/worker/

ENTRYPOINT ["/usr/local/bin/fuzzing-pool-launch"]
CMD ["/home/worker/launch-grizzly.sh"]
