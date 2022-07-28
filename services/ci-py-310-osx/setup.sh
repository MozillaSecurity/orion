#!/bin/sh
set -e -x

sed -E -i '' 's/^( *HOMEBREW_MACOS_VERSION=)".*"$/\1"10.15.7"/' "$HOMEBREW_PREFIX/Library/Homebrew/brew.sh"

brew install --force-bottle openssl@1.1 python@3.10
# shellcheck disable=SC2016
sed -i '' 's,export PATH=\\",&${HOMEBREW_PREFIX}/opt/python@3.10/libexec/bin:${HOMEBREW_PREFIX}/opt/python@3.10/bin:${HOMEBREW_PREFIX}/opt/python@3.10/Frameworks/Python.framework/Versions/3.10/bin:,' homebrew/Library/Homebrew/cmd/shellenv.sh
PATH="$HOMEBREW_PREFIX/opt/python@3.10/libexec/bin:$HOMEBREW_PREFIX/opt/python@3.10/bin:$HOMEBREW_PREFIX/opt/python@3.10/Frameworks/Python.framework/Versions/3.10/bin:$PATH"

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

# install utils to match linux ci images
python -m pip install tox
python -m pip install poetry
python -m pip install pre-commit

rm -rf homebrew/docs
cp -r orion/services/orion-decision orion-decision
cp orion/scripts/relocate_homebrew.sh homebrew/bin/
python -m pip install ./orion-decision
cp orion/recipes/linux/py-ci.sh .
rm -rf "$(brew --cache)"
relocate_homebrew.sh
tar -jcvf homebrew.tar.bz2 homebrew py-ci.sh pip
