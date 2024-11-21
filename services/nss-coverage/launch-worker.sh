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

if [[ ! -e .fuzzmanagerconf ]] && [[ "$NO_REPORT" != "1" ]]; then
  # Get fuzzmanager configuration from TC
  get-tc-secret fuzzmanagerconf .fuzzmanagerconf

  # Update fuzzmanager config for this instance
  mkdir -p signatures
  cat >> .fuzzmanagerconf <<- EOF
	sigdir = $HOME/signatures
	tool = nss-coverage
	EOF
  setup-fuzzmanager-hostname
  chmod 0600 .fuzzmanagerconf
fi

update-ec2-status "[$(date -Iseconds)] setup: getting revisions"
REVISION="$(retry-curl --compressed https://community-tc.services.mozilla.com/api/index/v1/task/project.fuzzing.coverage-revision.latest/artifacts/public/coverage-revision.txt)"
NSS_TAG="$(retry-curl "https://hg.mozilla.org/mozilla-central/raw-file/$REVISION/security/nss/TAG-INFO")"
NSPR_TAG="$(retry-curl "https://hg.mozilla.org/mozilla-central/raw-file/$REVISION/nsprpub/TAG-INFO")"

if [[ ! -d clang ]]; then
  update-ec2-status "[$(date -Iseconds)] setup: installing clang"
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
update-ec2-status "[$(date -Iseconds)] setup: cloning nss"
if [[ ! -d nspr ]]; then
  retry hg clone -r "$NSPR_TAG" https://hg.mozilla.org/projects/nspr
fi
if [[ ! -d nss ]]; then
  retry hg clone -r "$NSS_TAG" https://hg.mozilla.org/projects/nss
fi

# Clone cryptofuzz
update-ec2-status "[$(date -Iseconds)] setup: cloning cryptofuzz"
if [[ ! -d cryptofuzz ]]; then
  git-clone https://github.com/guidovranken/cryptofuzz.git
fi

COVRUNTIME=${COVRUNTIME-3600}

function clone-corpus {
  local name=$1
  local url=$2
  shift 2

  mkdir -p corpus
  pushd corpus
  if [[ ! -d "$name" ]]; then
    mkdir "$name"
    pushd "$name"

    # There may be no OSS-Fuzz corpus yet for new fuzz targets
    code=$(retry-curl --no-fail -w "%{http_code}" -O "$url")
    if [[ $code -eq 200 ]]; then
      unzip public.zip
    else
      echo "WARNING - cloning corpus for $name failed with code: $code" >&2
    fi
    rm public.zip

    popd
  fi
  popd
}

function clone-nssfuzz-corpus {
  local name="$1"
  shift 1

  clone-corpus "$name" \
               "https://storage.googleapis.com/nss-backup.clusterfuzz-external.appspot.com/corpus/libFuzzer/nss_$name/public.zip"
}

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
    > coverage-nss.json
  RUST_BACKTRACE=1 grcov nspr \
    -t coveralls+ \
    --token NONE \
    --commit-sha "$REVISION" \
    --guess-directory-when-missing \
    -s nspr/Debug/dist/include/nspr/ \
    -p "$PWD" \
    --path-mapping nspr_map.json \
    > coverage-nspr.json
  python merge-coverage.py coverage-nss.json coverage-nspr.json > "coverage-$name.json"
  rm coverage-nss.json coverage-nspr.json

  if [[ "$NO_REPORT" != "1" ]]; then
    # Submit coverage data
    cov-reporter \
      --repository mozilla-central \
      --description "libFuzzer (nss-$name,rt=$COVRUNTIME)" \
      --tool "nss-$name" \
      --submit "coverage-$name.json"
  fi
}

function run-nssfuzz-target {
  local target="$1"
  local name="$2"
  shift 2

  readarray -t options < <(python libfuzzer-options.py nss/fuzz/options/"$name".options)
  run-target "dist/Debug/bin/nssfuzz-$target" "$name" "${options[@]}"
}

declare -A targets=()
declare -A tls_targets=()

for file in nss/fuzz/options/*; do
  name="$(basename "$file" .options)"
  if [[ "$name" =~ -no_fuzzer_mode$ ]]; then
    tls_targets["${name%-no_fuzzer_mode}"]=1
    continue
  fi

  targets["$name"]=1
done

total_targets=$(("${#targets[@]}" + "${#tls_targets[@]}"))
curr_target_n=1

# Build nss with tls fuzzing mode
update-ec2-status "[$(date -Iseconds)] building nss with tls fuzzing mode ($curr_target_n/$total_targets have run)"
pushd nss
time ./build.sh -c -v --fuzz=tls --disable-tests
popd

# For each nssfuzz target with tls fuzzing mode, clone corpus & run
for target in "${!tls_targets[@]}"; do
  update-ec2-status "[$(date -Iseconds)] cloning corpus for $target ($curr_target_n/$total_targets)"
  clone-nssfuzz-corpus "$target"

  update-ec2-status "[$(date -Iseconds)] running $target ($curr_target_n/$total_targets)"
  run-nssfuzz-target "$target" "$target"
  ((curr_target_n++))
done

# Build nss w/o tls fuzzing mode
update-ec2-status "[$(date -Iseconds)] building nss w/o tls fuzzing mode"
pushd nss
time ./build.sh -c -v --fuzz --disable-tests
popd

# For each nssfuzz target w/o tls fuzzing mode, clone corpus & run
for target in "${!targets[@]}"; do
  name="$target"
  if [[ -n "${tls_targets[$target]:-}" ]]; then
    name="$name-no_fuzzer_mode"
  fi

  update-ec2-status "[$(date -Iseconds)] cloning corpus for $name ($curr_target_n/$total_targets)"
  clone-nssfuzz-corpus "$name"

  update-ec2-status "[$(date -Iseconds)] running $name ($curr_target_n/$total_targets)"
  run-nssfuzz-target "$target" "$name"
  ((curr_target_n++))
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

update-ec2-status "[$(date -Iseconds)] building cryptofuzz nss module"
pushd modules/nss
time make -j"$(nproc)"
popd

# Build cryptofuzz
export LIBFUZZER_LINK="-fsanitize=fuzzer"

update-ec2-status "[$(date -Iseconds)] building cryptofuzz"
time make -j"$(nproc)"
popd

# Clone cryptofuzz nss corpus
update-ec2-status "[$(date -Iseconds)] cloning cryptofuzz nss corpus"
clone-corpus "cryptofuzz" \
             "https://storage.googleapis.com/cryptofuzz-backup.clusterfuzz-external.appspot.com/corpus/libFuzzer/cryptofuzz_cryptofuzz-nss/public.zip"

# Run cryptofuzz
update-ec2-status "[$(date -Iseconds)] running cryptofuzz"
run-target "cryptofuzz/cryptofuzz" "cryptofuzz" --force-module=nss

update-ec2-status "[$(date -Iseconds)] done"
