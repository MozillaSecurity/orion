#!/usr/bin/env bash
set -e -x -o pipefail

retry() {
  i=0
  while [[ $i -lt 9 ]]; do
    if "$@"; then return; else sleep 30; fi
    i="$((i + 1))"
  done
  "$@"
}
retry-curl() { curl -sSL --connect-timeout 25 --fail --retry 5 -w "%{stderr}[downloaded %{url_effective}]\n" "$@"; }

# base msys packages
retry pacman --noconfirm -Sy \
  mingw-w64-x86_64-curl \
  patch \
  psmisc \
  tar \
  unzip
pacman --noconfirm -Scc
killall -TERM gpg-agent || true
pacman --noconfirm -Rs psmisc

# get node.js
VER=18.18.2
retry-curl "https://nodejs.org/dist/v${VER}/node-v${VER}-win-x64.zip" -o node.zip
unzip node.zip
rm node.zip
rm -rf msys64/opt/node
mkdir -p msys64/opt
mv "node-v${VER}-win-x64" msys64/opt/node
PATH="$PWD/msys64/opt/node:$PATH"
which node
node -v
npm -v

mkdir -p .ssh
retry ssh-keyscan github.com >.ssh/known_hosts

rm -rf \
  msys64/mingw64/share/doc/ \
  msys64/mingw64/share/info/ \
  msys64/mingw64/share/man/ \
  msys64/usr/share/doc/ \
  msys64/usr/share/info/ \
  msys64/usr/share/man/
# Delete symlinks
find msys64 -type l -delete
tar -jcvf msys2.tar.bz2 --hard-dereference msys64 .ssh
