FROM mozillasecurity/ci-node-12:latest

COPY recipes/linux /tmp/recipes
COPY services/domino-web-tests/setup.sh /tmp/recipes

USER root
# Install taskcluster CLI
RUN /tmp/recipes/setup.sh && rm -rf /tmp/recipes

COPY services/domino-web-tests/launch.sh /home/worker
COPY services/domino-web-tests/ssh_config /home/worker/.ssh/config

USER worker

CMD ["/home/worker/launch.sh"]
