#!/usr/bin/env bash
set -e -x -o pipefail

retry() {
  i=0
  while [[ $i -lt 9 ]]; do
    if "$@"; then return; else sleep 30; fi
    i="${i+1}"
  done
  "$@"
}
retry-curl() { curl -sSL --connect-timeout 25 --fail --retry 5 -w "%{stderr}[downloaded %{url_effective}]\n" "$@"; }

PYTHON_VERSION=3.12.8
STANDALONE_RELEASE=20250115
PYTHON_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${STANDALONE_RELEASE}/cpython-${PYTHON_VERSION}+${STANDALONE_RELEASE}-x86_64-apple-darwin-install_only_stripped.tar.gz"

mkdir -p "$HOMEBREW_PREFIX/opt"
retry-curl "$PYTHON_URL" | tar -C "$HOMEBREW_PREFIX/opt" -xvz
rm -rf "$HOMEBREW_PREFIX"/opt/python/lib/tcl* "$HOMEBREW_PREFIX"/opt/python/lib/tk* "$HOMEBREW_PREFIX"/opt/python/share

# shellcheck disable=SC2016
sed -i '' 's,export PATH=\\",&${HOMEBREW_PREFIX}/opt/python/bin:,' homebrew/Library/Homebrew/cmd/shellenv.sh
PATH="$HOMEBREW_PREFIX/opt/python/bin:$PATH"

# configure pip
mkdir -p pip
cat <<EOF >pip/pip.ini
[global]
disable-pip-version-check = true
no-cache-dir = false

[list]
format = columns

[install]
upgrade-strategy = only-if-needed
progress-bar = off
EOF
export PIP_CONFIG_FILE="$PWD/pip/pip.ini"

# install utils to match linux ci images
retry python -m pip install tox
retry python -m pip install poetry
retry python -m pip install pre-commit
retry-curl https://uploader.codecov.io/latest/macos/codecov -o homebrew/bin/codecov
chmod +x homebrew/bin/codecov

mkdir -p .ssh
retry ssh-keyscan github.com >.ssh/known_hosts

rm -rf homebrew/docs
cp -r orion/services/orion-decision orion-decision
cp orion/scripts/relocate_homebrew homebrew/bin/
python -m pip install ./orion-decision
relocate_homebrew
tar -jcvf homebrew.tar.bz2 homebrew pip .ssh
