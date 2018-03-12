FROM taskclusterprivate/fuzzos:latest

LABEL maintainer Christoph Diehl <cdiehl@mozilla.com>

COPY setup.sh .

USER root
RUN \
  apt-get update -q \
  && apt-get install -y -q --no-install-recommends --no-install-suggests \
    wget \
    unzip \
    subversion \
    gcc \
    libudev-dev \
    pkg-config \
  && apt-get clean -y \
  && apt-get autoclean -y \
  && apt-get autoremove -y \
  && rm -rf /var/lib/apt/lists/ \
  && rm -rf /root/.cache/* \
  && chown -R worker:worker /home/worker

ENTRYPOINT ["./setup.sh"]
