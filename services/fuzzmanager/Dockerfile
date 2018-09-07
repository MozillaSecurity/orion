FROM python:3.6-slim-stretch

LABEL maintainer Gary Kwong <gkwong@mozilla.com>

RUN useradd -d /home/fuzzmanager -s /bin/bash -m fuzzmanager
WORKDIR /home/fuzzmanager
ENV DEBIAN_FRONTEND noninteractive

COPY recipes /tmp/recipes

RUN \
  echo "deb http://ftp.us.debian.org/debian testing main contrib non-free" >> /etc/apt/sources.list \
  && apt-get update -qq \
  && apt-get install -y -qq --no-install-recommends --no-install-suggests \
    apache2-utils \
    apt-utils \
    git \
    locales \
    python3-pip \
    python3-setuptools \
  && echo "en_US.UTF-8 UTF-8" > /etc/locale.gen \
  && locale-gen en_US.UTF-8 \
  && cd /tmp/ \
  && LANG=en_US.UTF8 LC_ALL=en_US.UTF-8 \
     /tmp/recipes/fuzzmanager.sh \
  && rm -rf /tmp/* \
  && rm -rf /usr/share/man/ /usr/share/info/ \
  && find /usr/share/doc -depth -type f ! -name copyright -exec rm {} + || true \
  && find /usr/share/doc -empty -exec rmdir {} + || true \
  && apt-get clean -y \
  && apt-get autoclean -y \
  && apt-get autoremove -y \
  && rm -rf /var/lib/apt/lists/* \
  && rm -rf /root/.cache/*

ENV USER      fuzzmanager
ENV HOME      /home/fuzzmanager
ENV LOGNAME   fuzzmanager
ENV HOSTNAME  fuzzmanager
ENV LANG      en_US.UTF-8
ENV LC_ALL    en_US.UTF-8

RUN chown -R fuzzmanager:fuzzmanager /home/fuzzmanager
USER fuzzmanager
COPY launch-fuzzmanager.sh /home/fuzzmanager/
CMD ["/home/fuzzmanager/launch-fuzzmanager.sh"]
