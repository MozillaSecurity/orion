#!/bin/sh
set -e -x

# base msys packages
pacman-key --init
pacman-key --populate msys2
pacman --noconfirm -Sy \
  mingw-w64-x86_64-curl \
  patch \
  psmisc \
  tar \
  unzip
killall -TERM gpg-agent
rm -rf /var/cache/pacman/pkg

# get node.js
VER=14.17.3
curl -sSL "https://nodejs.org/dist/v${VER}/node-v${VER}-win-x64.zip" -o node.zip
unzip node.zip
rm node.zip
rm -rf msys64/opt/node
mkdir -p msys64/opt
mv "node-v${VER}-win-x64" msys64/opt/node
PATH="$PWD/msys64/opt/node:$PATH"
which node
node -v
npm -v

rm -rf msys64/mingw64/share/man/ msys64/mingw64/share/doc/ msys64/usr/share/doc/ msys64/usr/share/man/
tar -jcvf msys2.tar.bz2 --hard-dereference msys64
