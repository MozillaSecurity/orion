FROM mozillasecurity/fuzzos:latest

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

USER root
COPY ddebs.list /etc/apt/sources.list.d/
RUN \
  apt-get update -qq \
  && apt-get dist-upgrade -y \
  && apt-get install -q -y \
    libasound2 \
    libcurl3 \
    libegl1-mesa-dbgsym \
    libgl1-mesa-dri-dbgsym \
    libgl1-mesa-glx-dbgsym \
    libglapi-mesa-dbgsym \
    libglu1-mesa \
    libglu1-mesa-dbgsym \
    libosmesa6 \
    libosmesa6-dbgsym \
    libpulse0 \
    libwayland-egl1-mesa-dbgsym \
    mesa-va-drivers-dbgsym \
    nodejs \
    p7zip-full \
    python-dev \
    python-setuptools \
    python-wheel \
    screen \
    subversion \
    ubuntu-restricted-addons \
    unzip \
    virtualenv \
    wget \
    xvfb \
    zip \
  && apt-get install -q -y --no-install-recommends \
    build-essential \
    gdb \
    libcairo2-dbgsym \
    libgtk-3-0 \
    libgtk-3-0-dbgsym \
    mercurial \
    nano \
    python-pip \
    valgrind \
  && apt-get clean -y \
  && apt-get autoclean -y \
  && apt-get autoremove -y \
  && rm -rf /var/lib/apt/lists/* \
  && rm -rf /root/.cache/* \
  && pip install \
    psutil \
    git+https://github.com/cgoldberg/xvfbwrapper.git
COPY recipes/ /tmp/recipes/
RUN /tmp/recipes/grcov.sh \
  && /tmp/recipes/radamsa.sh \
  && rm -rf /tmp/recipes \
  && chown -R worker:worker /home/worker

USER worker
COPY config/ /home/worker/config/
COPY targets/ /home/worker/targets/
CMD ["/home/worker/config/run.sh"]
