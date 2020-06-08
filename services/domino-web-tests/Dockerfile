FROM mozillasecurity/ci-node-12:latest

COPY services/domino-web-tests/launch.sh /home/worker
COPY services/domino-web-tests/ssh_config /home/worker/.ssh/config

USER root
# Install taskcluster CLI
RUN curl --retry 5 -sSL "https://github.com/taskcluster/taskcluster/releases/download/v30.1.0/taskcluster-linux-amd64" -o /usr/local/bin/taskcluster \
  && chmod +x /usr/local/bin/taskcluster
USER worker

CMD ["/home/worker/launch.sh"]
