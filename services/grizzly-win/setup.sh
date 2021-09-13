#!/bin/sh
set -e -x

# base msys packages
pacman-key --init
pacman-key --populate msys2
pacman --noconfirm -Sy \
  mingw-w64-x86_64-curl \
  openssh \
  p7zip \
  patch \
  psmisc \
  tar \
  zstd
killall -TERM gpg-agent
rm -rf /var/cache/pacman/pkg

# get nuget
curl -sSL "https://aka.ms/nugetclidl" -o msys64/usr/bin/nuget.exe

# get fluentbit
VER=1.7.3
curl -sSLO "https://fluentbit.io/releases/1.7/td-agent-bit-${VER}-win64.zip"
7z x "td-agent-bit-${VER}-win64.zip"
mv "td-agent-bit-${VER}-win64" td-agent-bit
rm -rf td-agent-bit/include td-agent-bit/bin/fluent-bit.pdb

# get minidump_stackwalk
curl -sSLO "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.cache.level-1.toolchains.v3.win32-minidump-stackwalk.latest/artifacts/public/build/minidump_stackwalk.tar.zst"
zstdcat minidump_stackwalk.tar.zst | tar xv
mv minidump_stackwalk/minidump_stackwalk.exe msys64/usr/bin
rm -rf minidump_stackwalk minidump_stackwalk.tar.zst

# get python
VER=3.8.9
nuget install python -ExcludeVersion -OutputDirectory . -Version "$VER"
rm -rf msys64/opt/python
mkdir -p msys64/opt
mv python/tools msys64/opt/python
rm -rf python
PATH="$PWD/msys64/opt/python:$PWD/msys64/opt/python/Scripts:$PATH"
which python
python -V

# patch pip to workaround https://github.com/pypa/pip/issues/4368
sed -i "s/^\\(    \\)maker = PipScriptMaker(.*/&\r\n\\1maker.executable = '\\/usr\\/bin\\/env python'/" \
  msys64/opt/python/Lib/site-packages/pip/_internal/operations/install/wheel.py

# configure pip
mkdir -p pip
cat << EOF > pip/pip.ini
[global]
disable-pip-version-check = true
no-cache-dir = false

[list]
format = columns

[install]
upgrade-strategy = only-if-needed
progress-bar = off
EOF

# force-upgrade pip to include the above patch
# have to use `python -m pip` until PATH is updated externally
# otherwise /usr/bin/env will select the old `pip` in mozbuild
python -m pip install --upgrade --force-reinstall pip

# patch new pip to workaround https://github.com/pypa/pip/issues/4368
sed -i "s/^\\(    \\)maker = PipScriptMaker(.*/&\r\n\\1maker.executable = '\\/usr\\/bin\\/env python'/" \
  msys64/opt/python/Lib/site-packages/pip/_internal/operations/install/wheel.py

# get node.js
VER=14.17.3
curl -sSL "https://nodejs.org/dist/v${VER}/node-v${VER}-win-x64.zip" -o node.zip
7z x node.zip
rm node.zip
rm -rf msys64/opt/node
mkdir -p msys64/opt
mv "node-v${VER}-win-x64" msys64/opt/node
PATH="$PWD/msys64/opt/node:$PATH"
which node
node -v
curl -qL https://www.npmjs.com/install.sh | npm_install="7.22.0" sh
npm -v

# install utils to match linux ci images
python -m pip install \
  psutil \
  virtualenv \
  git+https://github.com/cgoldberg/xvfbwrapper.git

rm -rf msys64/mingw64/share/man/ msys64/mingw64/share/doc/ msys64/usr/share/doc/ msys64/usr/share/man/
cp orion/services/grizzly-win/launch.sh .

cp -r orion/services/fuzzing-decision fuzzing-decision
python -m pip install ./fuzzing-decision
tar -jcvf msys2.tar.bz2 --hard-dereference msys64 launch.sh pip td-agent-bit
