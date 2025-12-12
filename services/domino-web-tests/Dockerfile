FROM mozillasecurity/ci-node-22:latest

COPY recipes/linux /tmp/recipes
COPY services/domino-web-tests/setup.sh /tmp/recipes

USER root
COPY services/domino-web-tests/ssh_config /home/worker/.ssh/config

# Install taskcluster CLI
RUN /tmp/recipes/setup.sh && rm -rf /tmp/recipes

COPY services/domino-web-tests/launch.sh /home/worker

USER worker

CMD ["/home/worker/launch.sh"]
