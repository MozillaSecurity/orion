FROM ubuntu:22.04

COPY \
    recipes/linux/cleanup.sh \
    recipes/linux/common.sh \
    recipes/linux/fluentbit.sh \
    recipes/linux/fuzzing_tc.sh \
    recipes/linux/fuzzmanager.sh \
    recipes/linux/taskcluster.sh \
    recipes/linux/taskgraph-m-c-latest.sh \
    services/nyx/setup.sh \
    services/nyx/clang.sh \
    /srv/repos/setup/
COPY services/fuzzing-decision /srv/repos/fuzzing-decision
RUN /srv/repos/setup/setup.sh
COPY \
    services/nyx/launch-root.sh \
    services/nyx/launch-worker.sh \
    services/nyx/snapshot.sh \
    /home/worker/
COPY services/nyx/sharedir /home/worker/sharedir
WORKDIR /home/worker
ENTRYPOINT ["/usr/local/bin/fuzzing-pool-launch"]
CMD ["/home/worker/launch-root.sh"]
