FROM mozillasecurity/fuzzos:latest

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

USER root
COPY recipes/ /tmp/recipes/
RUN /tmp/recipes/grizzly.sh \
    && rm -rf /tmp/recipes

USER worker
COPY launch-grizzly.sh /home/worker/
CMD ["/home/worker/launch-grizzly.sh"]
