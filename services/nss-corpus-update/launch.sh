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
export GIT_AUTHOR_NAME="Taskcluster Automation"
export GIT_COMMITTER_NAME="Taskcluster Automation"

# Update github nss fuzzing corpus repo
for file in nss/fuzz/options/*; do
  name="$(basename "$file" ".options")"

  mkdir -p "nss-fuzzing-corpus/$name"
  pushd "nss-fuzzing-corpus/$name"

  code=$(retry-curl --no-fail -w "%{http_code}" -o /tmp/public.zip \
    "https://storage.googleapis.com/nss-backup.clusterfuzz-external.appspot.com/corpus/libFuzzer/nss_$name/public.zip")
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

# Build nss for corpus collection
pushd nss
./build.sh -c -v
popd

# Install frida
export PATH=$PATH:/home/worker/.local/bin
pipx install nss/fuzz/config/frida_corpus

# Create corpus directories
mkdir -p ./nss-fuzzing-corpus-new
mkdir -p ./nss-fuzzing-corpus-new-and-minimized

# Replace all binaries with frida wrapper
for binary in ./dist/Debug/bin/*; do
  mv "$binary" "${binary}_bin"
  cat >"$binary" <<EOF
#!/usr/bin/env bash
frida-corpus \
    --script $PWD/nss/fuzz/config/frida_corpus/hooks.js \
    --nss-build $PWD/dist/Debug/ \
    --program $PWD/${binary}_bin \
    --output $PWD/nss-fuzzing-corpus-new -- \$@
EOF
  chmod +x "$binary"
done

# Get list of hosts to collect handshakes
retry-curl -L -O https://tranco-list.eu/top-1m-incl-subdomains.csv.zip
unzip top-1m-incl-subdomains.csv.zip

shuf -n "${NUM_RAND_HOSTS-1250}" top-1m.csv | awk -F"," '{ print $2 }' >hosts.txt

# Collect corpus from tstclnt with random domains
tr -d '\r' <hosts.txt | xargs -P 5 -I {} bash -c \
  "readarray -t arguments < <(python ./nss/fuzz/config/tstclnt_arguments.py) && \
     (timeout -k 3 3 dist/Debug/bin/tstclnt -o -D -Q -b -h {} \${arguments[@]} || true)"

# Collect corpus from tests
pushd nss/tests
DOMSUF="localdomain" \
  HOST="localhost" \
  NSS_TESTS="bogo cert gtests sdr smime ssl ssl_gtests" \
  NSS_CYCLES="standard" ./all.sh || true
popd

# Build nss w/o tls fuzzing mode
pushd nss
./build.sh -c -v --fuzz --disable-tests
popd

# Minimize w/o tls fuzzing mode
for directory in nss-fuzzing-corpus-new/*; do
  name="$(basename "$directory")"
  corpus="$name"

  # The same target is also compiled with tls fuzzing mode, append
  # "-no_fuzzer_mode" to the corpus name.
  if [[ -f "nss/fuzz/options/$name-no_fuzzer_mode.options" ]]; then
    corpus="$name-no_fuzzer_mode"
  fi

  mkdir -p "nss-fuzzing-corpus-new-and-minimized/$corpus"
  dist/Debug/bin/nssfuzz-"$name" -merge=1 \
    "./nss-fuzzing-corpus-new-and-minimized/$corpus" "$directory"
done

# Build nss with tls fuzzing mode
pushd nss
./build.sh -c -v --fuzz=tls --disable-tests
popd

# Minimize with tls fuzzing mode
for directory in nss-fuzzing-corpus-new/*; do
  name="$(basename "$directory")"
  corpus="$name"

  if [[ -f "nss/fuzz/options/$name-no_fuzzer_mode.options" ]]; then
    mkdir -p "nss-fuzzing-corpus-new-and-minimized/$corpus"
    dist/Debug/bin/nssfuzz-"$name" -merge=1 \
      "./nss-fuzzing-corpus-new-and-minimized/$corpus" "$directory"
  fi
done

# Setup gcloud
mkdir -p ~/.config/gcloud
get-tc-secret ossfuzz-gutils ~/.config/gcloud/application_default_credentials.json raw
echo -e "[Credentials]\ngs_service_key_file = /home/worker/.config/gcloud/application_default_credentials.json" >.boto

# Upload to gcloud bucket
for directory in nss-fuzzing-corpus-new-and-minimized/*; do
  name="$(basename "$directory")"

  if [[ ! "$(ls "$directory")" ]]; then
    continue
  fi

  gsutil -m cp "$directory/*" \
    "gs://nss-corpus.clusterfuzz-external.appspot.com/libFuzzer/nss_$name"
done
