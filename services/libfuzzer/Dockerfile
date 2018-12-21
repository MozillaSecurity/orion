FROM mozillasecurity/fuzzos:latest

LABEL maintainer Christoph Diehl <cdiehl@mozilla.com>

USER root
RUN \
  apt-get update -qq \
  && apt-get install -y -qq --no-install-recommends --no-install-suggests \
    firefox \
    libpulse0 \
    subversion \
    screen \
  && "$HOME/.bin/cleanup.sh"

RUN chown -R worker:worker $HOME
USER $USER

COPY *.sh ./

CMD ["./setup.sh"]
