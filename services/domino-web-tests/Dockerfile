FROM node:22-slim

COPY recipes/linux /tmp/recipes
COPY services/domino-web-tests/setup.sh /tmp/recipes

USER root
COPY services/domino-web-tests/ssh_config /home/worker/.ssh/config

# Install taskcluster CLI
RUN /tmp/recipes/setup.sh && rm -rf /tmp/recipes

COPY services/domino-web-tests/launch.sh /home/worker
COPY recipes/linux/common.sh /home/worker/common.sh

USER worker
WORKDIR /home/worker

CMD ["/home/worker/launch.sh"]
