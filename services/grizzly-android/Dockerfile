FROM ubuntu:18.04 AS symbolizer-build

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

COPY recipes/ /tmp/recipes
WORKDIR /root
RUN /tmp/recipes/llvm-symbolizer.sh

FROM mozillasecurity/grizzly:latest

USER root
COPY recipes/ /tmp/recipes/
RUN /tmp/recipes/all.sh \
    && rm -rf /tmp/recipes
COPY recipes/kvm.sh /home/worker/

COPY --from=symbolizer-build /root/build/bin/llvm-symbolizer /home/worker/llvm-symbolizer
RUN chown worker:worker /home/worker/llvm-symbolizer

USER root
CMD ["/bin/sh", "-c", "/home/worker/kvm.sh && su worker -c /home/worker/launch-grizzly.sh"]
