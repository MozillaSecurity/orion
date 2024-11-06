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

# Setup github
get-tc-secret deploy-nss-fuzzing-corpus .ssh/nss_fuzzing_corpus_deploy

# Clone github nss fuzzing corpus repo
git-clone git@nss:MozillaSecurity/nss-fuzzing-corpus.git

export EMAIL=nobody@community-tc.services.mozilla.com
export {GIT_AUTHOR_NAME,GIT_COMMITTER_NAME}="Taskcluster Automation"

# Update github nss fuzzing corpus repo
for file in nss/fuzz/options/*; do
    name="$(basename "$file" ".options")"

    mkdir -p "nss-fuzzing-corpus/$name"
    pushd "nss-fuzzing-corpus/$name"

    code=$(retry-curl --no-fail -w "%{http_code}" -o /tmp/public.zip "https://storage.googleapis.com/nss-backup.clusterfuzz-external.appspot.com/corpus/libFuzzer/nss_$name/public.zip")
    if [[ $code -eq 200 ]]; then
      rm -rf ./*
      unzip /tmp/public.zip
    else
        echo "WARNING - cloning corpus for $name failed with code: $code" >&2
    fi
    rm -f /tmp/public.zip

    popd
done

# Commit and push any changes
pushd nss-fuzzing-corpus
if [[ "$(git status -s)" ]]; then
    git add -A
    git commit -m "nss-corpus-update: merge public oss-fuzz corpus"
    retry git push origin HEAD:master
fi
popd

# Build nss w/o tls fuzzing mode
pushd nss
# Can't use `--disable-tests` here, because we need the tstclnt for the
# handshake collection script
./build.sh -c -v --fuzz
popd

# Get list of hosts to collect handshakes
retry-curl -L -O https://tranco-list.eu/top-1m-incl-subdomains.csv.zip
unzip top-1m-incl-subdomains.csv.zip

shuf -n "${NUM_RAND_HOSTS-5000}" top-1m.csv | awk -F"," '{ print $2 }' > hosts.txt

# Run collection scripts
mkdir -p nss-new-corpus
mkdir -p nss-new-corpus-minimized

python nss/fuzz/config/collect_handshakes.py --nss-build ./dist/Debug \
                                             --hosts ./hosts.txt \
                                             --threads 5 \
                                             --output ./nss-new-corpus

# Minimize w/o tls fuzzing mode
for directory in nss-new-corpus/*; do
    name="$(basename "$directory" "-corpus")"
    corpus="$name-corpus"

    # The same target is also compiled with tls fuzzing mode, append
    # "-no_fuzzer_mode" to the corpus name.
    if [[ -f "nss/fuzz/options/$name-no_fuzzer_mode.options" ]]; then
        corpus="$name-no_fuzzer_mode-corpus"
    fi

    mkdir -p "nss-new-corpus-minimized/$corpus"
    dist/Debug/bin/nssfuzz-"$name" -merge=1 "./nss-new-corpus-minimized/$corpus" "$directory"
done

# Build nss with tls fuzzing mode
pushd nss
./build.sh -c -v --fuzz=tls --disable-tests
popd

# Minimize with tls fuzzing mode
for directory in nss-new-corpus/*; do
    name="$(basename "$directory" "-corpus")"
    corpus="$name-corpus"

    if [[ -f "nss/fuzz/options/$name-no_fuzzer_mode.options" ]]; then
        mkdir -p "nss-new-corpus-minimized/$corpus"
        dist/Debug/bin/nssfuzz-"$name" -merge=1 "./nss-new-corpus-minimized/$corpus" "$directory"
    fi
done

# Setup gcloud
mkdir -p ~/.config/gcloud
get-tc-secret ossfuzz-gutils ~/.config/gcloud/application_default_credentials.json raw
echo -e "[Credentials]\ngs_service_key_file = /home/worker/.config/gcloud/application_default_credentials.json" > .boto

# Upload to gcloud bucket
for directory in nss-new-corpus-minimized/*; do
    name="$(basename "$directory" "-corpus")"
    gsutil -m cp "$directory/*" "gs://nss-corpus.clusterfuzz-external.appspot.com/libFuzzer/nss_$name"
done
