#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

function retry () {
  op="$(mktemp)"
  for _ in {1..9}; do
    if "$@" >"$op"; then
      cat "$op"
      rm "$op"
      return
    fi
    sleep 30
  done
  rm "$op"
  "$@"
}

function tc-get-secret () {
  TASKCLUSTER_ROOT_URL="${TASKCLUSTER_PROXY_URL-$TASKCLUSTER_ROOT_URL}" retry taskcluster api secrets get "project/fuzzing/$1"
}

# Get the deploy key for langfuzz-config from Taskcluster
tc-get-secret deploy-langfuzz | jshon -e secret -e key -u > /root/.ssh/id_rsa.langfuzz

chmod 0600 /root/.ssh/id_rsa.*

# Setup Key Identities
cat << EOF > /root/.ssh/config
Host langfuzz
Hostname github.com
IdentityFile /root/.ssh/id_rsa.langfuzz
EOF

# -----------------------------------------------------------------------------

cd /home/ubuntu

# Clone LangFuzz to get the distiller tool
retry git clone -v --no-single-branch --depth 1 git@langfuzz:MozillaSecurity/LangFuzz.git

DISTILLER=/home/ubuntu/LangFuzz/tools/tests/distiller.py
V8=/home/ubuntu/v8/test/mjsunit/
CHAKRA=/home/ubuntu/ChakraCore/test/
OUTPUT=/home/ubuntu/tests/
MC=/srv/jenkins/jobs/mozilla-central-clone/workspace
JITTESTS=/home/ubuntu/gecko-dev/js/src/jit-test/
JSTESTS=/home/ubuntu/gecko-dev/js/src/tests/

# Fetch a build for timeout testing later
retry python -mfuzzfetch --target js --debug -n debug64

# Clone all source repositories for their tests
retry git clone --depth 1 https://github.com/v8/v8
retry git clone --depth 1 https://github.com/Microsoft/ChakraCore
retry git clone --depth 1 https://github.com/mozilla/gecko-dev

# Compose tests
$DISTILLER --microsoft-chakra $CHAKRA --google-v8-mjsunit $V8 --mozilla-jstests $JSTESTS --mozilla-jittests $JITTESTS --output $OUTPUT

# Delete timeouts
$DISTILLER --delete-timeouts --test $OUTPUT --binary debug64/dist/bin/js

# Rebrand for fuzzing machines
# NOTE: This is only required if the packaging process uses a different base
# directory than `/home/ubunt/tests`.
#$DISTILLER --rebrand /home/ubuntu/tests --output $OUTPUT

# Create zip bundle
zip /jstests-distilled.zip -r tests
