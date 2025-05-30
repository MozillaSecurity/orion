#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
. /src/recipes/common.sh

# Get the deploy key for langfuzz-config from Taskcluster
get-tc-secret deploy-langfuzz .ssh/id_rsa.langfuzz

# Setup Key Identities
cat <<EOF >>.ssh/config
Host langfuzz
Hostname github.com
IdentityFile ~/.ssh/id_rsa.langfuzz
EOF

# -----------------------------------------------------------------------------

# Clone LangFuzz to get the distiller tool
git-clone git@langfuzz:MozillaSecurity/LangFuzz.git

DISTILLER=/home/ubuntu/LangFuzz/tools/tests/distiller.py
V8=/home/ubuntu/v8/test/mjsunit/
CHAKRA=/home/ubuntu/ChakraCore/test/
OUTPUT=/home/ubuntu/tests/
JITTESTS=/home/ubuntu/gecko-dev/js/src/jit-test/
JSTESTS=/home/ubuntu/gecko-dev/js/src/tests/

# Fetch a build for timeout testing later
retry fuzzfetch --target js --debug -n debug64
LD_LIBRARY_PATH="$(pwd)/debug64/dist/bin"
export LD_LIBRARY_PATH

# Clone all source repositories for their tests
git-clone https://github.com/v8/v8
git-clone https://github.com/Microsoft/ChakraCore
git-clone https://github.com/mozilla/gecko-dev

# Compose tests
$DISTILLER --microsoft-chakra $CHAKRA --google-v8-mjsunit $V8 --mozilla-jstests $JSTESTS --mozilla-jittests $JITTESTS --output $OUTPUT

# Delete timeouts
$DISTILLER --delete-timeouts --test $OUTPUT --binary debug64/dist/bin/js

# Rebrand for fuzzing machines
# NOTE: This is only required if the packaging process uses a different base
# directory than `/home/ubuntu/tests`.
#$DISTILLER --rebrand /home/ubuntu/tests --output $OUTPUT

# Create zip bundle
mkdir -p output
zip output/jstests-distilled.zip -r tests

# Cleanup
rm -Rf tests

## Legacy test bundle creation ##

TEST262_LIST=/home/ubuntu/LangFuzz/tools/tests/test262.list

# This is a hack to extract include directives for jit-tests and convert them to jstests shell.js style
(cd $JITTESTS && grep -rnl " include:" . | grep directives | while read -r f; do cp "lib/$(grep -E -m1 -o 'include:[a-zA-Z0-9\.\-]+' "$f" | sed -e 's/include://')" "${f/directives.txt/}shell.js"; done)

cp -R $JITTESTS $JSTESTS .

# Make a limited copy of test262 as it is too large to distribute it all
cd tests
rsync -rv --files-from $TEST262_LIST test262 test262-limited
rm -Rf test262
cd ..

zip output/jstests-legacy.zip -r jit-test tests
