#!/usr/bin/env bash
set -e -x -o pipefail

retry () { i=0; while [[ "$i" -lt 9 ]]; do if "$@"; then return; else sleep 30; fi; i="$((i+1))"; done; "$@"; }
retry-curl () { curl -sSL --connect-timeout 25 --fail --retry 5 -w "%{stderr}[downloaded %{url_effective}]\n" "$@"; }

# base msys packages
retry pacman --noconfirm -Sy \
  mingw-w64-x86_64-curl \
  patch \
  psmisc \
  tar
pacman --noconfirm -Scc
killall -TERM gpg-agent || true
pacman --noconfirm -Rs psmisc

# get nuget
retry-curl "https://aka.ms/nugetclidl" -o msys64/usr/bin/nuget.exe

# get python
VER=3.12.0
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

# install utils to match linux ci images
retry python -m pip install tox
retry python -m pip install poetry
retry python -m pip install pre-commit
retry-curl https://uploader.codecov.io/latest/windows/codecov.exe -o msys64/usr/bin/codecov.exe

rm -rf \
  msys64/mingw64/share/doc/ \
  msys64/mingw64/share/info/ \
  msys64/mingw64/share/man/ \
  msys64/usr/share/doc/ \
  msys64/usr/share/info/ \
  msys64/usr/share/man/
cp -r orion/services/orion-decision orion-decision
retry python -m pip install ./orion-decision
cp orion/recipes/linux/py-ci.sh .
# Delete symlinks
find msys64 -type l -delete
tar -jcvf msys2.tar.bz2 --hard-dereference msys64 py-ci.sh pip
