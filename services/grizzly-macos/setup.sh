#!/bin/sh
set -e -x

brew install --force-bottle openssl@1.1 python@3.9
chmod +w "$HOMEBREW_PREFIX/lib/python3.9/site-packages"
# shellcheck disable=SC2016
sed -i '' 's,export PATH=\\",&${HOMEBREW_PREFIX}/opt/python@3.9/libexec/bin:${HOMEBREW_PREFIX}/opt/python@3.9/bin:${HOMEBREW_PREFIX}/opt/python@3.9/Frameworks/Python.framework/Versions/3.9/bin:,' "$HOMEBREW_PREFIX/Library/Homebrew/cmd/shellenv.sh"
PATH="$HOMEBREW_PREFIX/opt/python@3.9/libexec/bin:$HOMEBREW_PREFIX/opt/python@3.9/bin:$HOMEBREW_PREFIX/opt/python@3.9/Frameworks/Python.framework/Versions/3.9/bin:$PATH"

brew install --force-bottle p7zip zstd
brew install --force-bottle fluent-bit
brew install --force-bottle apr-util gettext subversion

brew install --force-bottle node@14
# shellcheck disable=SC2016
sed -i '' 's,export PATH=\\",&${HOMEBREW_PREFIX}/opt/node@14/bin:,' "$HOMEBREW_PREFIX/Library/Homebrew/cmd/shellenv.sh"
PATH="$HOMEBREW_PREFIX/opt/node@14/bin:$PATH"
curl -qL https://www.npmjs.com/install.sh | npm_install="7.22.0" sh

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
export PIP_CONFIG_FILE="$PWD/pip/pip.ini"

# get minidump_stackwalk
curl -sSL "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.cache.level-3.toolchains.v3.macosx64-minidump-stackwalk.latest/artifacts/public%2Fbuild%2Fminidump_stackwalk.tar.zst" | zstdcat | tar xv --strip 1 -C "$HOMEBREW_PREFIX/bin"

python -V
node -v
npm -v

# install utils to match linux ci images
python -m pip install \
  psutil \
  virtualenv

rm -rf "$HOMEBREW_PREFIX/docs"
find "$HOMEBREW_PREFIX" -path '*/share/doc' -exec rm -rf '{}' +
find "$HOMEBREW_PREFIX" -path '*/share/info' -exec rm -rf '{}' +
find "$HOMEBREW_PREFIX" -path '*/share/man' -exec rm -rf '{}' +

cp orion/scripts/relocate_homebrew.sh "$HOMEBREW_PREFIX/bin/"
cp orion/services/grizzly-macos/launch.sh .

cp -r orion/services/fuzzing-decision fuzzing-decision
python -m pip install ./fuzzing-decision

relocate_homebrew.sh
tar -jcvf homebrew.tar.bz2 homebrew pip launch.sh
