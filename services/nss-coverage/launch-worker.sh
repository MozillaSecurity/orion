#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source .local/bin/common.sh

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
export REVISION
NSS_TAG="$(retry-curl "https://hg.mozilla.org/mozilla-central/raw-file/$REVISION/security/nss/TAG-INFO")"
NSPR_TAG="$(retry-curl "https://hg.mozilla.org/mozilla-central/raw-file/$REVISION/nsprpub/TAG-INFO")"

if [[ ! -d clang ]]; then
  update-ec2-status "[$(date -Iseconds)] setup: installing clang"
  # resolve current clang toolchain
  retry-curl -O "https://hg.mozilla.org/mozilla-central/raw-file/$REVISION/taskcluster/ci/toolchain/clang.yml"
  python3 <<- "EOF" > clang.txt
	import yaml
	with open("clang.yml") as fd:
	  data = yaml.load(fd, Loader=yaml.CLoader)
	for tc, defn in data.items():
	  if defn.get("run", {}).get("toolchain-alias", {}).get("by-project", {}).get("default") == "linux64-clang":
	    print(tc)
	    break
	else:
	  raise Exception("No linux64-clang toolchain found")
	EOF
  CLANG_INDEX="$(cat clang.txt)"
  rm clang.txt clang.yml

  # install clang
  retry-curl "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.cache.level-3.toolchains.v3.$CLANG_INDEX.latest/artifacts/public/build/clang.tar.zst" | zstdcat | tar -x
  retry-curl "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.cache.level-3.toolchains.v3.${CLANG_INDEX/clang/x64-compiler-rt}.latest/artifacts/public/build/compiler-rt-x86_64-unknown-linux-gnu.tar.zst" | zstdcat | tar --strip-components=1 -C clang/lib/clang/* -x
fi
CC="$PWD/clang/bin/clang"
CXX="$PWD/clang/bin/clang++"
export CC
export CXX
$CC --version

CFLAGS="-O2 -g --coverage"
CXXFLAGS="$CFLAGS"
LDFLAGS="$CFLAGS"
export CFLAGS
export CXXFLAGS
export LDFLAGS

# clone nss/nspr
update-ec2-status "[$(date -Iseconds)] setup: cloning nss"
if [[ ! -d nspr ]]; then
  retry hg clone -r "$NSPR_TAG" https://hg.mozilla.org/projects/nspr
fi
if [[ ! -d nss ]]; then
  retry hg clone -r "$NSS_TAG" https://hg.mozilla.org/projects/nss
fi

# download corpus
update-ec2-status "[$(date -Iseconds)] setup: downloading corpus"
mkdir -p corpus
cd corpus
tls_targets=()
non_tls_targets=()
for p in ../nss/fuzz/options/*; do
  fuzzer="$(basename "$p" .options)"
  if [[ "$fuzzer" = "${fuzzer%-no_fuzzer_mode}" ]]; then
    tls_targets+=("$fuzzer")
  else
    non_tls_targets+=("${fuzzer%-no_fuzzer_mode}")
  fi
  if [[ ! -d "$fuzzer" ]]; then
    retry-curl -O "https://storage.googleapis.com/nss-backup.clusterfuzz-external.appspot.com/corpus/libFuzzer/nss_$fuzzer/public.zip"
    mkdir "$fuzzer"
    cd "$fuzzer"
    unzip ../public.zip
    cd ..
    rm public.zip
  fi
done
cd ..

COVRUNTIME=${COVRUNTIME-3600}

function run-target {
  target="$1"
  corpus="$2"
  shift 2

  find . -name "*.gcda" -delete
  timeout -s 2 -k $((COVRUNTIME + 60)) $((COVRUNTIME + 30)) "./dist/Debug/bin/nssfuzz-$target" "corpus/$corpus" -max_total_time="$COVRUNTIME" || :

  # Collect coverage count data.
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
  python merge-coverage.py coverage-nss.json coverage-nspr.json > "coverage-$corpus.json"
  rm coverage-nss.json coverage-nspr.json

  if [[ "$NO_REPORT" != "1" ]]; then
    # Submit coverage data.
    python3 -m CovReporter \
      --repository mozilla-central \
      --description "libFuzzer (nss-$corpus,rt=$COVRUNTIME)" \
      --tool "nss-$corpus" \
      --submit "coverage-$corpus.json"
  fi
}

n_tls_targets="${#tls_targets[@]}"
n_non_tls_targets="${#non_tls_targets[@]}"
n_targets=$((n_tls_targets + n_non_tls_targets))
cur_target=1

# build tls-mode targets
update-ec2-status "[$(date -Iseconds)] building tls-mode targets (0/$n_targets have run)"
rm -rf dist nss/out nspr/Debug
cd nss
time ./build.sh -c -v --fuzz --fuzz=tls --disable-tests
cd ..

# run each tls-mode target
for target in "${tls_targets[@]}"; do
  update-ec2-status "[$(date -Iseconds)] running target $target ($cur_target/$n_targets)"
  run-target "$target" "$target"
  ((cur_target++))
done

# build non-tls-mode targets
update-ec2-status "[$(date -Iseconds)] building non-tls-mode targets ($n_tls_targets/$n_targets have run)"
rm -rf dist nss/out nspr/Debug
cd nss
time ./build.sh -c -v --fuzz --disable-tests
cd ..

# run each non-tls-mode target
for target in "${non_tls_targets[@]}"; do
  update-ec2-status "[$(date -Iseconds)] running target $target-no_fuzzer_mode ($cur_target/$n_targets)"
  run-target "$target" "$target-no_fuzzer_mode"
  ((cur_target++))
done

update-ec2-status "[$(date -Iseconds)] done"
