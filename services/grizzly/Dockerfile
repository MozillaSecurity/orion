# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM ubuntu:18.04

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

ENV USER            worker
ENV HOME            /home/worker
ENV LOGNAME         worker
ENV HOSTNAME        taskcluster-worker
ENV DEBIAN_FRONTEND noninteractive

RUN useradd -d $HOME -s /bin/bash -m $USER

COPY recipes/linux/ /tmp/recipes/
COPY services/grizzly/setup.sh /tmp/recipes/
COPY base/linux/etc/pip.conf /etc/pip.conf
RUN /tmp/recipes/setup.sh \
    && rm -rf /tmp/recipes /tmp/setup.sh
COPY services/grizzly/screenlog-to-cloudwatch.py /usr/local/bin/
COPY services/grizzly/rwait.py /usr/local/bin/rwait
COPY services/grizzly/launch-grizzly.sh /home/worker/
COPY services/grizzly/launch-grizzly-worker.sh /home/worker/

ENV LANG   en_US.UTF-8
ENV LC_ALL en_US.UTF-8

WORKDIR $HOME
ENTRYPOINT ["/usr/local/bin/fuzzing-pool-launch"]
CMD ["/home/worker/launch-grizzly.sh"]
