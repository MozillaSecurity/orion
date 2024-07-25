#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source ~/.local/bin/common.sh

eval "$(ssh-agent -s)"
mkdir -p .ssh

pushd /src/fuzzmanager >/dev/null
  retry git fetch -q --depth 1 --no-tags origin master
  git reset --hard origin/master
popd >/dev/null

# Get fuzzmanager configuration from TC
get-tc-secret fuzzmanagerconf-site-scout .fuzzmanagerconf

# Update fuzzmanager config for this instance
mkdir -p signatures
cat >> .fuzzmanagerconf << EOF
sigdir = $HOME/signatures
EOF
setup-fuzzmanager-hostname
chmod 0600 .fuzzmanagerconf

# Install site-scout
update-ec2-status "Setup: installing site-scout"
retry python3 -m pip install fuzzfetch git+https://github.com/MozillaSecurity/site-scout

# Clone site-scout private
# only clone if it wasn't already mounted via docker run -v
if [[ ! -d /src/site-scout-private ]]; then
  update-ec2-status "Setup: cloning site-scout-private"

  # Get deployment key from TC
  get-tc-secret deploy-site-scout-private .ssh/id_ecdsa.site-scout-private

  cat <<- EOF >> .ssh/config

	Host site-scout-private
	HostName github.com
	IdentitiesOnly yes
	IdentityFile ~/.ssh/id_ecdsa.site-scout-private
	EOF

  # Checkout site-scout-private
  git-clone git@site-scout-private:MozillaSecurity/site-scout-private.git /src/site-scout-private
fi

update-ec2-status "Setup: fetching build"

# select build
TARGET_BIN="./build/firefox"
if [[ -n "$COVERAGE" ]]; then
  export COVERAGE_FLAG="--coverage"
  retry python3 -m fuzzfetch -n build --fuzzing --coverage
  export ARTIFACT_ROOT="https://community-tc.services.mozilla.com/api/index/v1/task/project.fuzzing.coverage-revision.latest/artifacts/public"
  SOURCE_URL="$(resolve-url "$ARTIFACT_ROOT/source.zip")"
  export SOURCE_URL

  REVISION="$(retry-curl --compressed "$ARTIFACT_ROOT/coverage-revision.txt")"
  export REVISION

  export GCOV_PREFIX="$HOME/build"
  GCOV_PREFIX_STRIP="$(grep pathprefix "${TARGET_BIN}.fuzzmanagerconf" | grep -E -o "/.+$" | tr -cd '/' | wc -c)"
  export GCOV_PREFIX_STRIP
else
  export COVERAGE_FLAG=""
  echo "Build types: ${BUILD_TYPES}"
  BUILD_SELECT_SCRIPT="import random;print(random.choice(str.split('${BUILD_TYPES}')))"
  build="$(python3 -c "$BUILD_SELECT_SCRIPT")"
  # download build
  case $build in
    asan32)
      # TEMPORARY workaround for frequent OOMs
      export ASAN_OPTIONS=malloc_context_size=20:rss_limit_heap_profile=false:max_malloc_fill_size=4096:quarantine_size_mb=64
      retry python3 -m fuzzfetch -n build --fuzzing --asan --cpu x86
      ;;
    debug32)
      retry python3 -m fuzzfetch -n build --fuzzing --debug --cpu x86
      ;;
    *)
      retry python3 -m fuzzfetch -n build --fuzzing "--$build"
      ;;
  esac
fi

# setup reporter
echo "No report yet" > status.txt
python3 -m TaskStatusReporter --report-from-file status.txt --keep-reporting 60 &
# shellcheck disable=SC2064
trap "kill $!; python3 -m TaskStatusReporter --report-from-file status.txt" EXIT

# select URL collections
mkdir active_lists
for LIST in $URL_LISTS
do
    cp "/src/site-scout-private/visit-yml/${LIST}" ./active_lists/
done

# create directory for launch failure results
mkdir -p /tmp/site-scout/local-results

update-ec2-status "Setup: launching site-scout"
python3 -m site_scout "$TARGET_BIN" -i ./active_lists/ --status-report status.txt --time-limit "$TIME_LIMIT" --memory-limit "$MEM_LIMIT" --jobs "$JOBS" --url-limit "$URL_LIMIT" --fuzzmanager -o /tmp/site-scout/local-results $COVERAGE_FLAG

if [[ -n "$COVERAGE" ]]; then
  retry-curl --compressed -O "$SOURCE_URL"
  unzip source.zip

  # Collect coverage count data.
  RUST_BACKTRACE=1 grcov "$GCOV_PREFIX" \
      -t coveralls+ \
      --commit-sha "$REVISION" \
      --token NONE \
      --guess-directory-when-missing \
      --ignore-not-existing \
      -p "$(rg -Nor '$1' "pathprefix = (.*)" "$HOME/${TARGET_BIN}.fuzzmanagerconf")" \
      -s "./mozilla-central-${REVISION}" \
      > "./coverage.json"

  # Submit coverage data.
  python3 -m CovReporter \
      --repository "mozilla-central" \
      --description "site-scout (10k subset)" \
      --tool "site-scout" \
      --submit "./coverage.json"
fi
