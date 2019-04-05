#!/bin/bash -ex
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -o pipefail

# Setup the Ubuntu debug symbol server (https://wiki.ubuntu.com/DebuggingProgramCrash)
cat << EOF > /etc/apt/sources.list.d/ddebs.list
deb http://ddebs.ubuntu.com/ $(lsb_release -cs) main restricted universe multiverse
deb http://ddebs.ubuntu.com/ $(lsb_release -cs)-updates main restricted universe multiverse
deb http://ddebs.ubuntu.com/ $(lsb_release -cs)-proposed main restricted universe multiverse
EOF

curl -sL http://ddebs.ubuntu.com/dbgsym-release-key.asc | apt-key add -
#apt-get install ubuntu-dbgsym-keyring
#apt-key adv --keyserver keyserver.ubuntu.com --recv-keys F2EDC64DC5AEE1F6B9C621F0C8CAB6595FDFF622

apt-get update -y -qq

packages=(
    libasound2
    libdbus-glib-1-2
    libglu1-mesa
    libosmesa6
    libpulse0
    mercurial
    p7zip-full
    python-dev
    python-wheel
    screen
    subversion
    ubuntu-restricted-addons
    virtualenv
    wget
    zip
)

packages_with_recommends=(
    build-essential
    gdb
    libgtk-3-0
    valgrind
)

dbgsym_packages=(
    libcairo2
    libegl1
    libegl-mesa0
    libgl1
    libgl1-mesa-dri
    libglapi-mesa
    libglu1-mesa
    libglvnd0
    libglx-mesa0
    libglx0
    libgtk-3-0
    libosmesa6
    libwayland-egl1
    mesa-va-drivers
    mesa-vdpau-drivers
)

apt-get install -q -y "${packages[@]}"
apt-get install -q -y --no-install-recommends "${packages_with_recommends[@]}"

# We want full symbols for things GTK/Mesa related where we find crashes.
# For each package, install the corresponding dbgsym package (same version).
dbgsym_installs=()
for pkg in "${dbgsym_packages[@]}"; do
    if ver="$(dpkg-query -W "$pkg" 2>/dev/null | cut -f2)"; then
        dbgsym_installs+=("$pkg-dbgsym=$ver")
    else
        echo "WARNING: $pkg not installed, but we checked for dbgsyms?" 1>&2
    fi
done
if [ ${#dbgsym_installs[@]} -ne 0 ]; then
    apt-get install -q -y "${dbgsym_installs[@]}"
fi

/tmp/recipes/redis.sh
/tmp/recipes/radamsa.sh

apt-get clean -y
apt-get autoclean -y
apt-get autoremove -y

rm -rf /var/lib/apt/lists/*
rm -rf /root/.cache/*

# otherwise setup-grizzly.sh fails
pip uninstall -y numpy
pip install \
    psutil \
    virtualenv \
    git+https://github.com/cgoldberg/xvfbwrapper.git

chown -R worker:worker /home/worker
