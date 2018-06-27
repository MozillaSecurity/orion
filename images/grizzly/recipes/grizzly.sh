#!/bin/bash -ex

# shellcheck disable=SC1091
. /etc/lsb-release
cat << EOF >/etc/apt/sources.list.d/ddebs.list
deb http://ddebs.ubuntu.com/ $DISTRIB_CODENAME main restricted universe multiverse
deb http://ddebs.ubuntu.com/ $DISTRIB_CODENAME-updates main restricted universe multiverse
deb http://ddebs.ubuntu.com/ $DISTRIB_CODENAME-proposed main restricted universe multiverse
EOF
apt-key adv --keyserver keyserver.ubuntu.com --recv-keys C8CAB6595FDFF622
apt-get update -qq
apt-get install -q -y \
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
    redis-server \
    screen \
    subversion \
    ubuntu-restricted-addons \
    unzip \
    virtualenv \
    wget \
    xvfb \
    zip
apt-get install -q -y --no-install-recommends \
    build-essential \
    gdb \
    libcairo2-dbgsym \
    libgtk-3-0 \
    libgtk-3-0-dbgsym \
    mercurial \
    nano \
    python-hiredis \
    python-pip \
    valgrind
/tmp/recipes/radamsa.sh
apt-get clean -y
apt-get autoclean -y
apt-get autoremove -y
rm -rf /var/lib/apt/lists/*
rm -rf /root/.cache/*
pip install \
    psutil \
    git+https://github.com/cgoldberg/xvfbwrapper.git
chown -R worker:worker /home/worker
