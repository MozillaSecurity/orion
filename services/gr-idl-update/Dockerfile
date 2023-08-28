# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM mozillasecurity/ci-node-18:latest

LABEL maintainer Jason Kratzer <jkratzer@mozilla.com>

ENV LOGNAME         worker
ENV HOSTNAME        taskcluster-worker
ARG DEBIAN_FRONTEND=noninteractive

USER root
COPY recipes/linux/ /src/recipes/
COPY services/gr-idl-update/setup.sh /src/recipes/setup-gr-idl-update.sh
COPY services/gr-idl-update/ssh_config /home/worker/.ssh/config
COPY services/gr-idl-update/launch.sh /home/worker
RUN /src/recipes/setup-gr-idl-update.sh

USER worker
WORKDIR /home/worker
ENTRYPOINT ["/usr/bin/env"]
CMD ["/home/worker/launch.sh"]
