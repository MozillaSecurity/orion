FROM mozillasecurity/fuzzos:latest

LABEL maintainer Christoph Diehl <cdiehl@mozilla.com>

USER root
RUN \
  apt-get update -qq \
  && apt-get install -y -qq --no-install-recommends --no-install-suggests \
    firefox \
    libpulse0 \
    unzip \
    subversion \
  && apt-get clean -y \
  && apt-get autoclean -y \
  && apt-get autoremove -y \
  && rm -rf /var/lib/apt/lists/* \
  && rm -rf /root/.cache/* \
  && chown -R worker:worker /home/worker

USER worker
COPY setup.sh .
ENTRYPOINT ["./setup.sh"]
