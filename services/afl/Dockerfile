# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM ubuntu:22.04

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

COPY \
    recipes/linux/cleanup.sh \
    recipes/linux/common.sh \
    recipes/linux/fluentbit.sh \
    recipes/linux/fuzzfetch.sh \
    recipes/linux/fuzzing_tc.sh \
    recipes/linux/fuzzmanager.sh \
    recipes/linux/grcov.sh \
    recipes/linux/gsutil.sh \
    recipes/linux/js32_deps.sh \
    recipes/linux/llvm.sh \
    recipes/linux/llvm-cov.sh \
    recipes/linux/llvm-symbolizer.sh \
    recipes/linux/nodejs.sh \
    recipes/linux/prefpicker.sh \
    recipes/linux/sentry.sh \
    recipes/linux/taskcluster.sh \
    recipes/linux/taskgraph-m-c-latest.sh \
    recipes/linux/worker.sh \
    services/afl/setup.sh \
    /srv/repos/setup/
COPY services/fuzzing-decision /srv/repos/fuzzing-decision
COPY \
    services/afl/pyproject.toml \
    services/nyx/nyx_utils.py \
    /srv/repos/nyx_utils/
COPY services/nyx/patches/afl-cmin.diff /home/worker/patches/
RUN /srv/repos/setup/setup.sh
COPY \
    services/afl/launch-root.sh \
    services/afl/setup-target.sh \
    services/afl/launch-worker.sh \
    /home/worker/
WORKDIR /home/worker
ENTRYPOINT ["/usr/local/bin/fuzzing-pool-launch"]
CMD ["/home/worker/launch-root.sh"]
