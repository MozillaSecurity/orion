#!/bin/bash
set -e -x -o pipefail

URL="https://github.com/hadolint/hadolint/releases/download/v1.19.0/hadolint-Linux-x86_64"
CHECKSUM="5099a932032f0d2c708529fb7739d4b2335d0e104ed051591a41d622fe4e4cc4"
HADOLINT=~/.cache/orion/hadolint

function checksum () {
  python3 -c "import hashlib;print(hashlib.sha256(open('$HADOLINT','rb').read()).hexdigest())"
}

mkdir -p "$(dirname "$HADOLINT")"
if [[ -e "$HADOLINT" ]]
then
  if [[ "$(checksum)" != "$CHECKSUM" ]]
  then
    curl -sSL -z "$HADOLINT" -o "$HADOLINT" "$URL"
    [[ "$(checksum)" == "$CHECKSUM" ]]  # assert that checksum matches
    chmod +x "$HADOLINT"
  fi
else
  curl -sSL -o "$HADOLINT" "$URL"
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
