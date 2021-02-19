# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM mozillasecurity/grizzly:latest

LABEL maintainer Jason Kratzer <jkratzer@mozilla.com>

ENV LOGNAME         worker
ENV HOSTNAME        taskcluster-worker
ARG DEBIAN_FRONTEND=noninteractive

COPY recipes/linux /tmp/recipes
COPY services/bugmon/setup.sh /tmp/recipes

USER root

# Install taskcluster CLI
RUN /tmp/recipes/setup.sh && rm -rf /tmp/recipes

COPY services/bugmon/launch.sh /home/worker

USER worker
WORKDIR /home/worker
ENTRYPOINT ["/usr/bin/env"]
CMD ["/home/worker/launch.sh"]
