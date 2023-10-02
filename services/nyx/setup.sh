#!/usr/bin/env bash
set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

# Fix some packages
# ref: https://github.com/moby/moby/issues/1024
dpkg-divert --local --rename --add /sbin/initctl
ln -sf /bin/true /sbin/initctl

DEBIAN_FRONTEND="teletype"
export DEBIAN_FRONTEND

# Add unprivileged user
useradd --create-home --home-dir /home/worker --shell /bin/bash worker

pkgs=(
  ca-certificates
  curl
  gcc
  git
  jshon
  lbzip2
  libglib2.0-0
  libjpeg-turbo8
  libpixman-1-0
  libpng16-16
  libxml2
  netcat-openbsd
  openssh-client
  psmisc
  python3
  python3-dev
  python3-pip
  python3-setuptools
  python3-wheel
  python3-distutils
  zstd
)

sys-update
apt-install-auto make
sys-embed "${pkgs[@]}"

mkdir -p /root/.ssh /home/worker/.ssh /home/worker/.local/bin
retry ssh-keyscan github.com | tee -a /root/.ssh/known_hosts /home/worker/.ssh/known_hosts > /dev/null

SRCDIR=/srv/repos/fuzzing-decision "${0%/*}/fuzzing_tc.sh"
"${0%/*}/fluentbit.sh"
"${0%/*}/taskcluster.sh"
source "${0%/*}/clang.sh"

function git-clone-rev () {
  local dest rev url
  url="$1"
  rev="$2"
  if [[ $# -eq 3 ]]
  then
    dest="$3"
  else
    dest="$(basename "$1" .git)"
  fi
  git init "$dest"
  pushd "$dest" >/dev/null || return 1
  git remote add origin "$url"
  retry git fetch -q --depth 1 --no-tags origin "$rev"
  git -c advice.detachedHead=false checkout "$rev"
  popd >/dev/null || return 1
}

# build AFL++ w/ Nyx
apt-install-auto libgtk-3-dev pax-utils python3-msgpack python3-jinja2 cpio bzip2
pushd /srv/repos >/dev/null
git-clone-rev https://github.com/AFLplusplus/AFLplusplus 497ff5ff7962ee492fef315227366d658c637ab2
pushd AFLplusplus >/dev/null
retry-curl https://github.com/AFLplusplus/AFLplusplus/commit/009d9522d711757cd237ad66dfee3d6f1523deff.patch | git apply
retry-curl https://hg.mozilla.org/mozilla-central/raw-file/8ccfbd9588cf6dc09d2171fcff3f0b4a13a3e711/taskcluster/scripts/misc/afl-nyx.patch | git apply
make afl-fuzz afl-showmap
pushd nyx_mode >/dev/null
git submodule init
retry git submodule update --depth 1 --single-branch libnyx
retry git submodule update --depth 1 --single-branch packer
retry git submodule update --depth 1 --single-branch QEMU-Nyx
pushd QEMU-Nyx >/dev/null
git submodule init
retry git submodule update --depth 1 --single-branch capstone_v4
retry git submodule update --depth 1 --single-branch libxdc
export CAPSTONE_ROOT="$PWD/capstone_v4"
export LIBXDC_ROOT="$PWD/libxdc"
popd >/dev/null
./build_nyx_support.sh
popd >/dev/null
find . -name .git -type d -exec rm -rf '{}' +
find . -name \*.o -delete
find . -executable -type f -execdir strip '{}' + -o -true || true
popd >/dev/null
popd >/dev/null
apt-mark manual "$(dpkg -S /usr/lib/x86_64-linux-gnu/libpython3.\*.so.1 | cut -d: -f1)"

mkdir -p /srv/repos/ipc-research
chown -R worker:worker /home/worker /srv/repos

pushd /srv/repos >/dev/null
for r in fuzzfetch FuzzManager prefpicker guided-fuzzing-daemon; do
  git-clone "https://github.com/MozillaSecurity/$r"
  chown -R worker:worker "$r"
  # install then uninstall so only dependencies remain
  retry su worker -c "pip3 install ./$r"
  su worker -c "pip3 uninstall -y $r"
done
popd >/dev/null

retry su worker -c "pip3 install google-cloud-storage"
rm -rf /opt/clang /opt/rustc
/srv/repos/setup/cleanup.sh
