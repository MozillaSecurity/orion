#!/bin/sh
set -e -x

retry () { i=0; while [ $i -lt 9 ]; do if "$@"; then return; else sleep 30; fi; i="${i+1}"; done; "$@"; }

# base msys packages
retry pacman --noconfirm -S \
  mingw-w64-x86_64-curl \
  patch \
  psmisc \
  tar \
  unzip
pacman --noconfirm -Scc
killall -TERM gpg-agent || true
pacman --noconfirm -Rs psmisc

# get node.js
VER=14.21.1
curl --connect-timeout 25 --retry 5 -sSL "https://nodejs.org/dist/v${VER}/node-v${VER}-win-x64.zip" -o node.zip
unzip node.zip
rm node.zip
rm -rf msys64/opt/node
mkdir -p msys64/opt
mv "node-v${VER}-win-x64" msys64/opt/node
PATH="$PWD/msys64/opt/node:$PATH"
which node
node -v
curl --connect-timeout 25 --retry 5 -qL https://www.npmjs.com/install.sh | npm_install="7.24.2" sh
npm -v

rm -rf \
  msys64/mingw64/share/doc/ \
  msys64/mingw64/share/info/ \
  msys64/mingw64/share/man/ \
  msys64/usr/share/doc/ \
  msys64/usr/share/info/ \
  msys64/usr/share/man/
tar -jcvf msys2.tar.bz2 --hard-dereference msys64
