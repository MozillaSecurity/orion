#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source .local/bin/common.sh
# shellcheck source=recipes/linux/taskgraph-m-c-latest.sh
source /src/recipes/taskgraph-m-c-latest.sh

if [[ ! -e .fuzzmanagerconf ]] && [[ $NO_REPORT != "1" ]]; then
  # Get fuzzmanager configuration from TC
  get-tc-secret fuzzmanagerconf .fuzzmanagerconf

  # Update fuzzmanager config for this instance
  mkdir -p signatures
  cat >>.fuzzmanagerconf <<-EOF
	sigdir = $HOME/signatures
	tool = nss-coverage
	EOF
  setup-fuzzmanager-hostname
  chmod 0600 .fuzzmanagerconf
fi

if [[ ! -d clang ]]; then
  update-status "setup: installing clang"
  clang_ver="$(resolve-tc-alias clang)"
  compiler_ver="x64-compiler-rt-${clang_ver/clang-/}"
  retry-curl "$(resolve-tc "$clang_ver")" | zstdcat | tar -x
  retry-curl "$(resolve-tc "$compiler_ver")" | zstdcat | tar --strip-components=1 -C clang/lib/clang/* -x
fi

export CC="$PWD/clang/bin/clang"
export CXX="$PWD/clang/bin/clang++"
$CC --version

export CFLAGS="--coverage -O2 -g"
export CXXFLAGS="$CFLAGS"
export LDFLAGS="$CFLAGS"

# Clone nss/nspr
update-status "setup: cloning nss"

HG_REVISION="$(retry-curl --compressed https://community-tc.services.mozilla.com/api/index/v1/task/project.fuzzing.coverage-revision.latest/artifacts/public/coverage-revision.txt)"
GIT_REVISION="$(retry-curl --compressed https://lando.moz.tools/api/hg2git/firefox/$HG_REVISION | jshon -e "git_hash" -u)"

if [[ ! -d firefox ]]; then
  retry git clone --no-checkout --depth 1 --filter=tree:0 https://github.com/mozilla-firefox/firefox.git

  pushd firefox
  git fetch --depth 1 origin $GIT_REVISION
  git sparse-checkout set --no-cone /security/nss /nsprpub
  git checkout $GIT_REVISION
  popd

  mv firefox/security/nss nss
  mv firefox/nsprpub nspr
fi

# Clone cryptofuzz
update-status "setup: cloning cryptofuzz"
if [[ ! -d cryptofuzz ]]; then
  git-clone https://github.com/MozillaSecurity/cryptofuzz.git
fi

# Setup gcloud
mkdir -p ~/.config/gcloud
get-tc-secret ossfuzz-gutils ~/.config/gcloud/application_default_credentials.json raw
echo -e "[Credentials]\ngs_service_key_file = /home/worker/.config/gcloud/application_default_credentials.json" >.boto

COVRUNTIME=${COVRUNTIME-3600}

function run-target {
  local target="$1"
  local name="$2"
  shift 2

  find . -name "*.gcda" -delete
  timeout -s 2 -k $((COVRUNTIME + 60)) $((COVRUNTIME + 30)) \
    "$target" "corpus/$name" -max_total_time="$COVRUNTIME" "$@" || :

  # Collect coverage count data
  RUST_BACKTRACE=1 grcov nss \
    -t coveralls+ \
    --token NONE \
    --commit-sha "$REVISION" \
    --guess-directory-when-missing \
    -s nss/out/Debug/ \
    -p "$PWD" \
    >coverage-nss.json
  RUST_BACKTRACE=1 grcov nspr \
    -t coveralls+ \
    --token NONE \
    --commit-sha "$REVISION" \
    --guess-directory-when-missing \
    -s nspr/Debug/dist/include/nspr/ \
    -p "$PWD" \
    --path-mapping nspr_map.json \
    >coverage-nspr.json
  python merge-coverage.py coverage-nss.json coverage-nspr.json >"coverage-$name.json"
  rm coverage-nss.json coverage-nspr.json

  if [[ $NO_REPORT != "1" ]]; then
    # Submit coverage data
    cov-reporter \
      --repository mozilla-central \
      --description "libFuzzer (nss-$name,rt=$COVRUNTIME)" \
      --tool "nss-$name" \
      --submit "coverage-$name.json"
  fi
}

# Build nss w/o tls fuzzing mode
update-status "building nss w/o tls fuzzing mode"
pushd nss
time ./build.sh -c -v --fuzz --disable-tests
popd

for fuzzer in dist/Debug/bin/nssfuzz-*; do
  file="$(basename "$fuzzer")"
  name="${file#nssfuzz-}"

  if [[ -f "nss/fuzz/options/$name-no_fuzzer_mode.options" ]]; then
    name="${name}-no_fuzzer_mode"
  fi

  update-status "cloning corpus for target $name"
  mkdir -p "./corpus/$name"
  pushd "./corpus/$name"
  gsutil cp "gs://nss-backup.clusterfuzz-external.appspot.com/corpus/libFuzzer/nss_$name/latest.zip" .
  unzip latest.zip
  rm latest.zip
  popd

  update-status "running target $name"
  readarray -t options < <(python "nss/fuzz/config/libfuzzer-options.py nss/fuzz/options/$name.options")
  run-target "$fuzzer" "$name" "${options[@]}"
done

# Build nss with tls fuzzing mode
update-status "building nss with tls fuzzing mode"
pushd nss
time ./build.sh -c -v --fuzz=tls --disable-tests
popd

for fuzzer in dist/Debug/bin/nssfuzz-*; do
  file="$(basename "$fuzzer")"
  name="${file#nssfuzz-}"

  if [[ -f "nss/fuzz/options/$name-no_fuzzer_mode.options" ]]; then
    update-status "cloning corpus for target $name"
    mkdir -p "./corpus/$name"
    pushd "./corpus/$name"
    gsutil -m cp "gs://nss-backup.clusterfuzz-external.appspot.com/corpus/libFuzzer/nss_$name/latest.zip" .
    unzip latest.zip
    rm latest.zip
    popd

    update-status "running target $name"
    readarray -t options < <(python "nss/fuzz/config/libfuzzer-options.py nss/fuzz/options/$name.options")
    run-target "$fuzzer" "$name" "${options[@]}"
  fi
done

# Generate cryptofuzz headers
pushd cryptofuzz
./gen_repository.py

# Build cryptofuzz nss module
export NSS_NSPR_PATH="$HOME"
export CFLAGS="$CFLAGS -fsanitize=address,undefined,fuzzer-no-link"
export CXXFLAGS="$CXXFLAGS -fsanitize=address,undefined,fuzzer-no-link"
export CXXFLAGS="$CXXFLAGS -I $NSS_NSPR_PATH/dist/public/nss -I $NSS_NSPR_PATH/dist/Debug/include/nspr -DCRYPTOFUZZ_NSS -DCRYPTOFUZZ_NO_OPENSSL"
export LINK_FLAGS="$LINK_FLAGS -lsqlite3"

update-status "building cryptofuzz nss module"
pushd modules/nss
time make -j"$(nproc)"
popd

# Build cryptofuzz
export LIBFUZZER_LINK="-fsanitize=fuzzer"

update-status "building cryptofuzz"
time make -j"$(nproc)"
popd

# Clone cryptofuzz nss corpus
update-status "cloning cryptofuzz nss corpus"
mkdir -p ./corpus/cryptofuzz

pushd ./corpus/cryptofuzz
retry-curl -O "https://storage.googleapis.com/cryptofuzz-backup.clusterfuzz-external.appspot.com/corpus/libFuzzer/cryptofuzz_cryptofuzz-nss/public.zip"
unzip public.zip
rm -f public.zip
popd

# Run cryptofuzz
update-status "running cryptofuzz"
run-target "cryptofuzz/cryptofuzz" "cryptofuzz" --force-module=nss

update-status "done"
