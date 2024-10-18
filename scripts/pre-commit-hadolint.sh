#!/bin/bash
set -e -x -o pipefail

[[ "$(uname -m)" == "aarch64" ]] && ARCH="arm64" || ARCH="$(uname -m)"
URL="https://github.com/hadolint/hadolint/releases/download/v2.12.0/hadolint-Linux-$ARCH"
declare -A CHECKSUMS=(
  ["x86_64"]="56de6d5e5ec427e17b74fa48d51271c7fc0d61244bf5c90e828aab8362d55010"
  ["arm64"]="5798551bf19f33951881f15eb238f90aef023f11e7ec7e9f4c37961cb87c5df6"
)
CHECKSUM=${CHECKSUMS[$ARCH]}
HADOLINT=~/.cache/orion/hadolint

function checksum () {
  python3 -c "import hashlib;print(hashlib.sha256(open('$HADOLINT','rb').read()).hexdigest())"
}

function retry-curl () {
  curl --connect-timeout 25 --fail --location --retry 5 --show-error --silent --write-out "%{stderr}[downloaded %{url_effective}]\n" "$@"
}

mkdir -p "$(dirname "$HADOLINT")"
if [[ -e "$HADOLINT" ]]
then
  if [[ "$(checksum)" != "$CHECKSUM" ]]
  then
    retry-curl -o "$HADOLINT" "$URL"
    [[ "$(checksum)" == "$CHECKSUM" ]]  # assert that checksum matches
    chmod +x "$HADOLINT"
  fi
else
  retry-curl -o "$HADOLINT" "$URL"
  [[ "$(checksum)" == "$CHECKSUM" ]]  # assert that checksum matches
  chmod +x "$HADOLINT"
fi

exec "$HADOLINT" \
  --ignore DL3002 \
  --ignore DL3003 \
  --ignore DL3007 \
  --ignore DL3008 \
  --ignore DL3009 \
  --ignore DL3013 \
  --ignore DL3018 \
  --ignore DL4001 \
  --ignore DL4006 \
  "$@"
