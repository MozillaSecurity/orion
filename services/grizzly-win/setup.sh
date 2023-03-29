#!/bin/sh
set -e -x

retry () { i=0; while [ $i -lt 9 ]; do if "$@"; then return; else sleep 30; fi; i="${i+1}"; done; "$@"; }
retry_curl () { curl -sSL --connect-timeout 25 --fail --retry 5 "$@"; }

# base msys packages
retry pacman --noconfirm -S \
  mingw-w64-x86_64-curl \
  openssh \
  p7zip \
  patch \
  psmisc \
  subversion \
  tar \
  zstd
pacman --noconfirm -Scc
killall -TERM gpg-agent || true
pacman --noconfirm -Rs psmisc

# get nuget
retry_curl "https://aka.ms/nugetclidl" -o msys64/usr/bin/nuget.exe

# get fluentbit
VER=2.0.5
retry_curl -O "https://fluentbit.io/releases/2.0/fluent-bit-${VER}-win64.zip"
7z x "fluent-bit-${VER}-win64.zip"
mv "fluent-bit-${VER}-win64" td-agent-bit
rm -rf td-agent-bit/include td-agent-bit/bin/fluent-bit.pdb

# get new minidump-stackwalk
retry_curl -O "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.cache.level-3.toolchains.v3.win64-minidump-stackwalk.latest/artifacts/public/build/minidump-stackwalk.tar.zst"
zstdcat minidump-stackwalk.tar.zst | tar xv
mv minidump-stackwalk/minidump-stackwalk.exe msys64/usr/bin/
rm -rf minidump-stackwalk minidump-stackwalk.tar.zst
./msys64/usr/bin/minidump-stackwalk.exe --version

# get python
VER=3.10.10
retry nuget install python -ExcludeVersion -OutputDirectory . -Version "$VER"
rm -rf msys64/opt/python
mkdir -p msys64/opt
mv python/tools msys64/opt/python
rm -rf python
PATH="$PWD/msys64/opt/python:$PWD/msys64/opt/python/Scripts:$PATH"
which python
python -V

# install python dbg syms
for pkg in core exe lib; do
  retry_curl -O "https://www.python.org/ftp/python/$VER/amd64/${pkg}_pdb.msi"
  msiexec /i "${pkg}_pdb.msi" "TARGETDIR=$(cygpath -aw msys64/opt/python)" /quiet
  rm "${pkg}_pdb.msi"
done

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
retry python -m pip install --upgrade --force-reinstall pip

# patch new pip to workaround https://github.com/pypa/pip/issues/4368
sed -i "s/^\\(    \\)maker = PipScriptMaker(.*/&\r\n\\1maker.executable = '\\/usr\\/bin\\/env python'/" \
  msys64/opt/python/Lib/site-packages/pip/_internal/operations/install/wheel.py

# get windows debugging tools
retry_curl "https://go.microsoft.com/fwlink/?linkid=2173743" -o winsdksetup.exe
if ! ./winsdksetup /features OptionId.WindowsDesktopDebugger /quiet /installpath "$(cygpath -aw msys64/opt)"; then
  # shellcheck disable=SC2012
  cat "$(ls -tr "$TEMP/WindowsSDK" | tail -n1)"
  exit 1
fi

# install pyext
retry_curl "https://github.com/SeanCline/PyExt/releases/download/PyExt-v0.1.57/PyExt-x64-Release.zip" -o pyext.zip
7z x pyext.zip
mv x64/Release/pyext.dll msys64/opt/Debuggers/x64/winext/
rm -rf x64 pyext.zip

# get node.js
VER=18.14.2
retry_curl "https://nodejs.org/dist/v${VER}/node-v${VER}-win-x64.zip" -o node.zip
7z x node.zip
rm node.zip
rm -rf msys64/opt/node
mkdir -p msys64/opt
mv "node-v${VER}-win-x64" msys64/opt/node
PATH="$PWD/msys64/opt/node:$PATH"
which node
node -v
npm -v

# get grcov
retry_curl -O "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.cache.level-3.toolchains.v3.win64-grcov.latest/artifacts/public/build/grcov.tar.zst"
zstdcat grcov.tar.zst | tar --strip-components=1 -xv
mv grcov.exe msys64/usr/bin/
./msys64/usr/bin/grcov.exe --version

# install utils to match linux ci images
retry python -m pip install \
  psutil \
  virtualenv

rm -rf \
  msys64/mingw64/share/doc/ \
  msys64/mingw64/share/info/ \
  msys64/mingw64/share/man/ \
  msys64/usr/share/doc/ \
  msys64/usr/share/info/ \
  msys64/usr/share/man/
cp orion/services/grizzly-win/launch.sh .

cp -r orion/services/fuzzing-decision fuzzing-decision
retry python -m pip install ./fuzzing-decision
tar -jcvf msys2.tar.bz2 --hard-dereference msys64 launch.sh pip td-agent-bit
