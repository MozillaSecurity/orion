# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM ubuntu:22.04 as afl

COPY \
    recipes/linux/common.sh \
    recipes/linux/taskgraph-m-c-latest.sh \
    services/nyx/build_afl.sh \
    services/nyx/clang.sh \
    /srv/repos/setup/
COPY services/nyx/patches/ /srv/repos/setup/patches/
COPY services/nyx/custom_mutators/ /srv/repos/setup/custom_mutators/
RUN /srv/repos/setup/build_afl.sh

FROM ubuntu:22.04

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

COPY \
    recipes/linux/cleanup.sh \
    recipes/linux/common.sh \
    recipes/linux/fluentbit.sh \
    recipes/linux/fuzzfetch.sh \
    recipes/linux/fuzzing_tc.sh \
    recipes/linux/fuzzmanager.sh \
    recipes/linux/nodejs.sh \
    recipes/linux/prefpicker.sh \
    recipes/linux/sentry.sh \
    recipes/linux/taskcluster.sh \
    recipes/linux/taskgraph-m-c-latest.sh \
    services/nyx/clang.sh \
    services/nyx/setup.sh \
    /srv/repos/setup/
COPY services/fuzzing-decision /srv/repos/fuzzing-decision
COPY \
    services/nyx/pyproject.toml \
    services/nyx/nyx_ipc_manager.py \
    services/nyx/nyx_utils.py \
    services/nyx/setup.cfg \
    services/nyx/setup.py \
    /srv/repos/nyx_ipc_manager/
RUN /srv/repos/setup/setup.sh
COPY \
    services/nyx/launch-root.sh \
    services/nyx/launch-worker.sh \
    services/nyx/snapshot.sh \
    /home/worker/
COPY services/nyx/sharedir /home/worker/sharedir
COPY --from=afl /srv/repos/AFLplusplus /srv/repos/AFLplusplus
WORKDIR /home/worker
ENTRYPOINT ["/usr/local/bin/fuzzing-pool-launch"]
CMD ["/home/worker/launch-root.sh"]
