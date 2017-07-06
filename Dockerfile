FROM ubuntu:zesty

LABEL maintainer Christoph Diehl <cdiehl@mozilla.com>

RUN useradd -d /home/worker -s /bin/bash -m worker
WORKDIR /home/worker

RUN \
  apt-get update -q \
  && apt-get install -y -q --no-install-recommends --no-install-suggests \
    apt-utils \
    bzip2 \
    curl \
    dbus \
    git \
    locales \
    make \
    python \
    python-pip \
    python-setuptools \
    python3-pip \
    python3-setuptools \
    software-properties-common \
    ssh \
    xvfb \
  && apt-get clean -y \
  && apt-get autoclean -y \
  && apt-get autoremove -y \
  && rm -rf /var/lib/apt/lists/ \
  && rm -rf /root/.cache/*

RUN locale-gen en_US.UTF-8

ENV USER      worker
ENV HOME      /home/worker
ENV LOGNAME   worker
ENV HOSTNAME  taskcluster-worker
ENV LANG      en_US.UTF-8
ENV LC_ALL    en_US.UTF-8
ENV CC        clang
ENV CXX       clang++

COPY setup.sh /tmp
COPY recipes /tmp/recipes
RUN \
  cd /tmp/ \
  && ./setup.sh \
  && rm -rf /tmp/*

RUN \
  rm -rf /usr/share/man/ /usr/share/info/ \
  && find /usr/share/doc -depth -type f ! -name copyright | xargs rm || true \
  && find /usr/share/doc -empty | xargs rmdir || true \
  && apt-get clean -y \
  && apt-get autoclean -y \
  && apt-get autoremove -y \
  && rm -rf /var/lib/apt/lists/ \
  && rm -rf /root/.cache/*

RUN chown -R worker:worker /home/worker
USER worker

CMD ["/bin/bash", "--login"]
