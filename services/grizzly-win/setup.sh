#!/usr/bin/env bash
set -e -x -o pipefail
shopt -s extglob

retry () { i=0; while [[ "$i" -lt 9 ]]; do if "$@"; then return; else sleep 30; fi; i="$((i+1))"; done; "$@"; }
retry-curl () { curl -sSL --compressed --connect-timeout 25 --fail --retry 5 -w "%{stderr}[downloaded %{url_effective}]\n" "$@"; }

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
retry-curl "https://aka.ms/nugetclidl" -o msys64/usr/bin/nuget.exe

# get fluentbit
VER=2.1.10
retry-curl -O "https://fluentbit.io/releases/${VER/%.+([0-9])/}/fluent-bit-${VER}-win64.zip"
7z x "fluent-bit-${VER}-win64.zip"
mv "fluent-bit-${VER}-win64" td-agent-bit
rm -rf td-agent-bit/include td-agent-bit/bin/fluent-bit.pdb

# get python
VER=3.10.8
retry nuget install python -ExcludeVersion -OutputDirectory . -Version "$VER"
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
retry python -m pip install --upgrade --force-reinstall pip

# patch new pip to workaround https://github.com/pypa/pip/issues/4368
sed -i "s/^\\(    \\)maker = PipScriptMaker(.*/&\r\n\\1maker.executable = '\\/usr\\/bin\\/env python'/" \
  msys64/opt/python/Lib/site-packages/pip/_internal/operations/install/wheel.py

# get node.js
VER=18.18.2
retry-curl "https://nodejs.org/dist/v${VER}/node-v${VER}-win-x64.zip" -o node.zip
7z x node.zip
rm node.zip
rm -rf msys64/opt/node
mkdir -p msys64/opt
mv "node-v${VER}-win-x64" msys64/opt/node
PATH="$PWD/msys64/opt/node:$PATH"
which node
node -v
npm -v

retry-curl -O https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.v2.mozilla-central.latest.taskgraph.decision/artifacts/public/label-to-taskid.json
resolve_tc () {
python - "$1" << EOF
import json
import sys
with open("label-to-taskid.json") as fd:
  label_to_task = json.load(fd)
task_id = label_to_task[f"toolchain-win64-{sys.argv[1]}"]
print(f"https://firefox-ci-tc.services.mozilla.com/api/queue/v1/task/{task_id}/artifacts/public/build/{sys.argv[1]}.tar.zst")
EOF
}

# get grcov
retry-curl -O "$(resolve_tc grcov)"
zstdcat grcov.tar.zst | tar -xv
mv grcov/grcov.exe msys64/usr/bin/
rm -rf grcov grcov.tar.zst
./msys64/usr/bin/grcov.exe --version

# get new minidump-stackwalk
retry-curl -O "$(resolve_tc minidump-stackwalk)"
zstdcat minidump-stackwalk.tar.zst | tar xv
mv minidump-stackwalk/minidump-stackwalk.exe msys64/usr/bin/
rm -rf minidump-stackwalk minidump-stackwalk.tar.zst
./msys64/usr/bin/minidump-stackwalk.exe --version

rm label-to-taskid.json

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
