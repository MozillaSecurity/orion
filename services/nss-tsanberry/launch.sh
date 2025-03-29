#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source .local/bin/common.sh

# Clone nss/nspr
retry hg clone https://hg.mozilla.org/projects/nspr
retry hg clone https://hg.mozilla.org/projects/nss

# Build nss with --fuzz=tsan
pushd nss
./build.sh -c -v --fuzz=tsan --disable-tests
popd

# Setup fuzzmanger
get-tc-secret fuzzmanagerconf "$HOME/.fuzzmanagerconf"

# Setup gcloud
mkdir -p ~/.config/gcloud
get-tc-secret ossfuzz-gutils ~/.config/gcloud/application_default_credentials.json raw
echo -e "[Credentials]\ngs_service_key_file = /home/worker/.config/gcloud/application_default_credentials.json" > .boto

# Clone corpora
mkdir -p ./corpus/nss_tls-client-no_fuzzer_mode
mkdir -p ./corpus/nss_dtls-client-no_fuzzer_mode

pushd corpus/nss_tls-client-no_fuzzer_mode
gsutil cp "gs://nss-backup.clusterfuzz-external.appspot.com/corpus/libFuzzer/nss_tls-client-no_fuzzer_mode/latest.zip" .
unzip latest.zip
rm -f latest.zip
popd

pushd corpus/nss_dtls-client-no_fuzzer_mode
gsutil cp "gs://nss-backup.clusterfuzz-external.appspot.com/corpus/libFuzzer/nss_dtls-client-no_fuzzer_mode/latest.zip" .
unzip latest.zip
rm -f latest.zip
popd

# TSan setup
export TSAN_OPTIONS="halt_on_error=1 suppressions=$PWD/nss/fuzz/config/tsan.suppressions"

function check-for-crash() {
    local binary=$1

    if [ -f crash-* ]; then
        zip -r testcase.zip crash-*
        collector --submit --stdout stdout.log --crashdata stderr.log \
                  --binary $binary --tool nss-tsanberry \
                  --testcase testcase.zip
        rm -rf crash-* testcase.zip
    fi
}

# Run tls client target
BINARY="dist/Debug/bin/nsstsan-tls-client"
THREADS=$((2 + RANDOM % 25))
MAX_TIME=$((60 * 60 * 5))

timeout -k $((MAX_TIME + 300)) $((MAX_TIME + 300)) \
    $BINARY run ./corpus/nss_tls-client-no_fuzzer_mode $THREADS $MAX_TIME \
    > stdout.log 2> stderr.log || true
check-for-crash $BINARY

# Run dtls client target
BINARY="dist/Debug/bin/nsstsan-dtls-client"
THREADS=$((2 + RANDOM % 25))
MAX_TIME=$((60 * 60 * 5))

timeout -k $((MAX_TIME + 300)) $((MAX_TIME + 300)) \
    $BINARY run ./corpus/nss_dtls-client-no_fuzzer_mode $THREADS $MAX_TIME \
    > stdout.log 2> stderr.log || true
check-for-crash $BINARY

# Run database target
BINARY="dist/Debug/bin/nsstsan-database"
THREADS=$((2 + RANDOM % 25))
MAX_TIME=$((60 * 60 * 2))

timeout -k $((MAX_TIME + 300)) $((MAX_TIME + 300)) \
    $BINARY run $THREADS $MAX_TIME > stdout.log 2> stderr.log || true
check-for-crash $BINARY
