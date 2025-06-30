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
	tool = neqo-coverage
	EOF
  setup-fuzzmanager-hostname
  chmod 0600 .fuzzmanagerconf
fi

# Install clang, required to build NSS
update-status "setup: installing clang"
if [[ ! -d clang ]]; then
  clang_ver="$(resolve-tc-alias clang)"
  compiler_ver="x64-compiler-rt-${clang_ver/clang-/}"
  retry-curl "$(resolve-tc "$clang_ver")" | zstdcat | tar -x
  retry-curl "$(resolve-tc "$compiler_ver")" | zstdcat | tar --strip-components=1 -C clang/lib/clang/* -x
fi

export PATH="$PATH:$HOME/clang/bin"
export CC="$HOME/clang/bin/clang"
export CXX="$HOME/clang/bin/clang++"

# Install rust dev, required to build neqo
update-status "setup: installing rust-dev"
if [[ ! -d cargo ]]; then
  retry-curl "$(resolve-tc rust-dev)" | zstdcat | tar -x
fi

export PATH="$PATH:$HOME/rustc/bin"
export RUSTC="$HOME/rustc/bin/rustc"
export RUSTFLAGS="$RUSTFLAGS -Clinker=clang"

# Install cargo-fuzz, required to build neqo fuzz targets
update-status "setup: installing cargo-fuzz"
cargo install cargo-fuzz

# Clone nss/nspr
HG_REVISION="$(retry-curl --compressed https://community-tc.services.mozilla.com/api/index/v1/task/project.fuzzing.coverage-revision.latest/artifacts/public/coverage-revision.txt)"
GIT_REVISION="$(retry-curl --compressed https://lando.moz.tools/api/hg2git/firefox/$HG_REVISION | jshon -e "git_hash" -u)"

update-status "setup: cloning nss/nspr"
if [[ ! -d firefox ]]; then
  retry git clone --no-checkout --depth 1 --filter=tree:0 https://github.com/mozilla-firefox/firefox.git

  pushd firefox
  git fetch --depth 1 origin $GIT_REVISION
  git sparse-checkout set --no-cone /security/nss /nsprpub /third_party/rust/neqo-bin/Cargo.toml
  git checkout $GIT_REVISION
  popd

  mv firefox/security/nss nss
  mv firefox/nsprpub nspr
  mv firefox/third_party/rust/neqo-bin neqo-bin
fi

# Clone neqo
NEQO_VERSION="$(python package-version.py neqo-bin/Cargo.toml | tr -d "\n")"

update-status "setup: cloning neqo"
if [[ ! -d neqo ]]; then
  retry git clone --depth 1 --branch "v$NEQO_VERSION" https://github.com/mozilla/neqo.git
fi

# Build nss
update-status "setup: building nss"
pushd nss
./build.sh -c --opt --static --disable-tests
popd

# Build neqo
update-status "setup: building neqo"
pushd neqo
NSS_DIR="$HOME/nss" RUSTFLAGS="$RUSTFLAGS -Cinstrument-coverage" \
CARGO_PROFILE_RELEASE_LTO="false" \
  cargo fuzz build --release --debug-assertions
popd

# Setup gcloud
update-status "setup: pulling gcloud creds"
mkdir -p ~/.config/gcloud
get-tc-secret ossfuzz-gutils ~/.config/gcloud/application_default_credentials.json raw
echo -e "[Credentials]\ngs_service_key_file = /home/worker/.config/gcloud/application_default_credentials.json" > .boto

# Pull corpus & run fuzzer
BINARY_PATH="$HOME/neqo/target/x86_64-unknown-linux-gnu/release"
COVRUNTIME=${COVRUNTIME-3600}
NEQO_REVISION="$(git -C neqo rev-parse "v$NEQO_VERSION" | tr -d "\n")"

function clone-corpus {
  mkdir -p "$HOME/corpus/$1"

  pushd "$HOME/corpus/$1"
  gsutil cp "gs://neqo-backup.clusterfuzz-external.appspot.com/corpus/libFuzzer/neqo_$1/latest.zip" .
  unzip latest.zip
  rm -f latest.zip
  popd
}

function run-target {
  find . -name "*.profraw" -delete
  timeout -s 2 -k $((COVRUNTIME + 60)) $((COVRUNTIME + 30)) \
    "$BINARY_PATH/$1" "$HOME/corpus/$1" -max_total_time="$COVRUNTIME" || :

  RUST_BACKTRACE=1 grcov . \
    -t coveralls+ \
    --token NONE \
    --commit-sha "$NEQO_REVISION" \
    --guess-directory-when-missing \
    --binary-path "$BINARY_PATH" \
    --source-dir "$HOME/neqo" \
    --prefix-dir "$HOME/neqo" \
    --llvm-path "$HOME/clang/bin" \
    > coverage-neqo.json
  python map-coverage.py coverage-neqo.json > "coverage-$1.json"

  if [[ $NO_REPORT != "1" ]]; then
    # Submit coverage data
    cov-reporter \
      --repository mozilla-central \
      --description "cargo-fuzz (neqo-$1,rt=$COVRUNTIME)" \
      --tool "neqo-$1" \
      --submit "coverage-$1.json"
  fi
}

for fuzzer in neqo/fuzz/fuzz_targets/*.rs; do
  name="$(basename "$fuzzer" .rs)"

  update-status "fuzz: cloning corpus for $name"
  clone-corpus $name

  update-status "fuzz: running target $name"
  run-target $name
done

update-status "done"
