FROM mozillasecurity/grizzly:latest

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

USER root
COPY recipes/ /tmp/recipes/
RUN /tmp/recipes/all.sh \
    && rm -rf /tmp/recipes
COPY recipes/kvm.sh /home/worker/

USER root
CMD ["/bin/sh", "-c", "/home/worker/kvm.sh && su worker -c /home/worker/launch-grizzly.sh"]
