#!/bin/sh
set -e -x

# base msys packages
pacman --noconfirm -S \
  mingw-w64-x86_64-curl \
  patch \
  psmisc \
  tar
pacman --noconfirm -Scc
killall -TERM gpg-agent || true
pacman --noconfirm -Rs psmisc

# get nuget
curl -sSL "https://aka.ms/nugetclidl" -o msys64/usr/bin/nuget.exe

# get python
VER=3.9.10
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

# install utils to match linux ci images
python -m pip install tox
python -m pip install poetry
python -m pip install pre-commit

rm -rf \
  msys64/mingw64/share/doc/ \
  msys64/mingw64/share/info/ \
  msys64/mingw64/share/man/ \
  msys64/usr/share/doc/ \
  msys64/usr/share/info/ \
  msys64/usr/share/man/
cp -r orion/services/orion-decision orion-decision
python -m pip install ./orion-decision
cp orion/recipes/linux/py-ci.sh .
tar -jcvf msys2.tar.bz2 --hard-dereference msys64 py-ci.sh pip
