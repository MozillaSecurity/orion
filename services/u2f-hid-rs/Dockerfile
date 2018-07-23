FROM mozillasecurity/fuzzos:latest

LABEL maintainer Christoph Diehl <cdiehl@mozilla.com>

COPY setup.sh .

USER root
RUN \
  apt-get update -qq \
  && apt-get install -y -qq --no-install-recommends --no-install-suggests \
    unzip \
    subversion \
    gcc \
    libudev-dev \
    pkg-config \
  && apt-get clean -y \
  && apt-get autoclean -y \
  && apt-get autoremove -y \
  && rm -rf /var/lib/apt/lists/* \
  && rm -rf /root/.cache/* \
  && chown -R worker:worker /home/worker

ENTRYPOINT ["./setup.sh"]
