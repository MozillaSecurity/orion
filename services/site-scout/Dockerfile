# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM mozillasecurity/grizzly:latest

LABEL maintainer Jesse Schwartzentruber <jschwartzentruber@mozilla.com>

ENV LOGNAME         worker
ENV HOSTNAME        taskcluster-worker
ARG DEBIAN_FRONTEND=noninteractive

COPY services/site-scout/setup.sh /src/recipes/setup-site-scout.sh

RUN /src/recipes/setup-site-scout.sh

COPY services/site-scout/launch-root.sh services/site-scout/launch-worker.sh /home/worker/

WORKDIR /home/worker
ENTRYPOINT ["/usr/local/bin/fuzzing-pool-launch"]
CMD ["/home/worker/launch-root.sh"]
