FROM node:lts-slim

RUN apt-get update -yy \
  && apt-get install -yy --no-install-recommends git curl jshon \
  && rm -rf /var/apt/lists /var/log
COPY services/domino-web-tests/launch.sh /root
COPY services/domino-web-tests/ssh_config /root/.ssh/config

CMD ["/root/launch.sh"]
