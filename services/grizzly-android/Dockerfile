FROM mozillasecurity/grizzly:latest

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

USER root
COPY recipes/ /tmp/recipes/
RUN /tmp/recipes/all.sh \
    && rm -rf /tmp/recipes

USER worker
CMD ["/home/worker/launch-grizzly.sh"]
