#!/bin/sh
set -e -x

sed -E -i '' 's/^( *HOMEBREW_MACOS_VERSION=)".*"$/\1"10.15.7"/' "$HOMEBREW_PREFIX/Library/Homebrew/brew.sh"

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
curl -qL https://www.npmjs.com/install.sh | npm_install="7.24.2" sh

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

# get new minidump-stackwalk
curl -sSL "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.cache.level-3.toolchains.v3.macosx64-minidump-stackwalk.latest/artifacts/public/build/minidump-stackwalk.tar.zst" | zstdcat | tar xv --strip 1 -C "$HOMEBREW_PREFIX/bin"

# old minidump_stackwalk (remove when support for new is added to ffpuppet)
curl -sSL "https://tooltool.mozilla-releng.net/sha512/2105e384ffbf3459d91701207e879a676ab8e49ca1dc2b7bf1e7d695fb6245ba719285c9841429bbc6605ae4e710107621f788a7204ed681148115ccf64ac087" -o "$HOMEBREW_PREFIX/bin/minidump_stackwalk"
chmod +x "$HOMEBREW_PREFIX/bin/minidump_stackwalk"

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

rm -rf "$(brew --cache)"
relocate_homebrew.sh
tar -jcvf homebrew.tar.bz2 homebrew pip launch.sh
