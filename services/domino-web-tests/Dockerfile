FROM node:22-slim

COPY base/linux/etc/pip.conf /etc/pip.conf
COPY recipes/linux /src/recipes
COPY services/domino-web-tests/setup-worker.sh /src/recipes/setup-worker.sh
RUN /src/recipes/setup-worker.sh

WORKDIR /home/worker

COPY recipes/linux /tmp/recipes
COPY services/domino-web-tests/setup.sh /tmp/recipes

USER root
COPY services/domino-web-tests/ssh_config /home/worker/.ssh/config

# Install taskcluster CLI
RUN /tmp/recipes/setup.sh && rm -rf /tmp/recipes

COPY services/domino-web-tests/launch.sh /home/worker

USER worker

CMD ["/home/worker/launch.sh"]
