#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# required to run tools installed via pipx
PATH=~/.local/bin:$PATH

# shellcheck source=recipes/linux/common.sh
source common.sh

if [[ -n $QUEUE_NAME ]]; then
  # get gcp pubsub credentials
  mkdir -p ~/.config/gcloud
  get-tc-secret google-cloud-pubsub-site-scout-urls ~/.config/gcloud/application_default_credentials.json raw
fi

# create required artifact directory to avoid task failure
mkdir -p /tmp/site-scout

function calc-duration() {
  local duration
  if [[ -n $TASK_ID ]] || [[ -n $RUN_ID ]]; then
    duration="$(($(get-deadline) - $(date +%s) - 600))"
    # check if there is enough time to run
    if [[ $duration -le 600 ]]; then
      duration=-1
      update-status "Not enough time remaining before deadline!"
    fi
    if [[ -n $RUNTIME_LIMIT ]] && [[ $RUNTIME_LIMIT -lt $duration ]]; then
      duration="$RUNTIME_LIMIT"
    fi
  else
    # RUNTIME_LIMIT or no-limit
    duration="${RUNTIME_LIMIT-0}"
  fi
  echo "$duration"
}

TARGET_DURATION="$(calc-duration)"
if [[ $TARGET_DURATION -eq -1 ]]; then
  exit 0
fi

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
cat >>.fuzzmanagerconf <<EOF
sigdir = $HOME/signatures
EOF
setup-fuzzmanager-hostname
chmod 0600 .fuzzmanagerconf

# Install site-scout
update-status "Setup: installing site-scout"
retry pipx install site-scout

# Clone site-scout private
# only clone if it wasn't already mounted via docker run -v
if [[ ! -d /src/site-scout-private ]]; then
  update-status "Setup: cloning site-scout-private"

  # Get deployment key from TC
  get-tc-secret deploy-site-scout-private .ssh/id_ecdsa.site-scout-private

  cat <<-EOF >>.ssh/config

	Host site-scout-private
	HostName github.com
	IdentitiesOnly yes
	IdentityFile ~/.ssh/id_ecdsa.site-scout-private
	EOF

  # Checkout site-scout-private
  git-clone git@site-scout-private:MozillaSecurity/site-scout-private.git /src/site-scout-private
fi

update-status "Setup: collecting URLs"

extra_flags=()

if [[ -n $CRASH_STATS ]]; then
  # prepare to run URLs from Crash Stats
  python3 -m venv /tmp/crashstats-tools-venv
  retry /tmp/crashstats-tools-venv/bin/pip install crashstats-tools
  retry /tmp/crashstats-tools-venv/bin/pip install site-scout
  extra_flags+=("--omit-urls")
  set +x
  CRASHSTATS_API_TOKEN="$(get-tc-secret crash-stats-api-token)"
  set -x
  export CRASHSTATS_API_TOKEN
  # download allow list (top-1M.txt), this is temporary for initial test run
  python3 -m venv /tmp/tranco-venv
  retry /tmp/tranco-venv/bin/pip install tranco
  /tmp/tranco-venv/bin/python /src/site-scout-private/src/tranco_top_sites.py --lists top-1M
  # download crash-urls.jsonl from crash-stats.mozilla.org
  # NOTE: currently filtering by top 1M
  /tmp/crashstats-tools-venv/bin/python /src/site-scout-private/src/crash_stats_collector.py --allowed-domains top-1M.txt --include-path --scan-hours "$SCAN_HOURS"
  mkdir active_lists
  cp crash-urls.jsonl ./active_lists/
elif [[ -n $QUEUE_NAME ]]; then
  python3 -m venv /tmp/queue-list-venv
  retry /tmp/queue-list-venv/bin/pip install google-cloud-pubsub
  mkdir active_lists
else
  # prepare to run URL list
  # select URL collections
  mkdir active_lists
  for LIST in $URL_LISTS; do
    cp "/src/site-scout-private/visit-yml/${LIST}" ./active_lists/
  done
fi

update-status "Setup: fetching build"

# select build
TARGET_BIN="./build/firefox"
if [[ -n $COVERAGE ]]; then
  extra_flags+=("--coverage")
  retry fuzzfetch -n build --coverage
  export ARTIFACT_ROOT="https://community-tc.services.mozilla.com/api/index/v1/task/project.fuzzing.coverage-revision.latest/artifacts/public"
  SOURCE_URL="$(resolve-url "$ARTIFACT_ROOT/source.zip")"
  export SOURCE_URL

  REVISION="$(retry-curl --compressed "$ARTIFACT_ROOT/coverage-revision.txt")"
  export REVISION

  export GCOV_PREFIX="$HOME/build"
  GCOV_PREFIX_STRIP="$(grep pathprefix "${TARGET_BIN}.fuzzmanagerconf" | grep -E -o "/.+$" | tr -cd '/' | wc -c)"
  export GCOV_PREFIX_STRIP
elif [[ -n $CUSTOM_BUILD ]]; then
  echo "Using requested custom build"
  # shellcheck disable=SC2086
  retry fuzzfetch -n build $CUSTOM_BUILD
else
  echo "Build types: ${BUILD_TYPES}"
  BUILD_SELECT_SCRIPT="import random;print(random.choice(str.split('${BUILD_TYPES}')))"
  build="$(python3 -c "$BUILD_SELECT_SCRIPT")"
  # download build
  case $build in
    asan32)
      retry fuzzfetch -n build --asan --cpu x86
      ;;
    beta-asan)
      retry fuzzfetch -n build --asan --branch beta
      ;;
    debug32)
      retry fuzzfetch -n build --debug --cpu x86
      ;;
    *)
      retry fuzzfetch -n build "--$build"
      ;;
  esac
fi

# try to workaround frequent OOMs
export ASAN_OPTIONS="detect_stack_use_after_return=0\
:hard_rss_limit_mb=${MEM_LIMIT}\
:malloc_context_size=20\
:rss_limit_heap_profile=false"

# setup reporter
echo "No report yet" >status.txt
task-status-reporter --report-from-file status.txt --keep-reporting 60 &
# shellcheck disable=SC2064
trap "kill $!; task-status-reporter --report-from-file status.txt" EXIT

# enable page interactions
if [[ -n $EXPLORE ]]; then
  extra_flags+=("--explore" "$EXPLORE")
fi

# create directory for launch failure results
mkdir -p /tmp/site-scout/local-results

while true; do
  if [[ -n $QUEUE_NAME ]]; then
    python3 -m venv /tmp/queue-list-venv
    retry /tmp/queue-list-venv/bin/pip install google-cloud-pubsub
    # maximum ack time is 10 minutes or else queue entries will be retried,
    # so QUEUE_CHUNK_SIZE and JOBS should be set such that work can be
    # completed within 10 minutes
    urls="$(/tmp/queue-list-venv/bin/python /src/site-scout-private/src/queue_util.py pull "$QUEUE_NAME" --limit "$QUEUE_CHUNK_SIZE")"
    acks="$(basename "$urls" .txt).ack.txt"
    url-collection -l "$urls" active_lists/work.yml
    rm "$urls"
  fi

  TARGET_DURATION="$(calc-duration)"
  if [[ $TARGET_DURATION -eq -1 ]]; then
    exit 0
  fi

  update-status "Setup: launching site-scout"
  site-scout "$TARGET_BIN" \
    -i ./active_lists/ \
    "${extra_flags[@]}" \
    --fuzzmanager \
    --memory-limit "$MEM_LIMIT" \
    --jobs "$JOBS" \
    --runtime-limit "$TARGET_DURATION" \
    --status-report status.txt \
    --time-limit "$TIME_LIMIT" \
    --url-limit "${URL_LIMIT-0}" \
    -o /tmp/site-scout/local-results

  if [[ -n $QUEUE_NAME ]]; then
    /tmp/queue-list-venv/bin/python /src/site-scout-private/src/queue_util.py ack "$QUEUE_NAME" "$acks"
    rm active_lists/* "$acks"
  else
    break
  fi
done

if [[ -n $COVERAGE ]]; then
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
    >"./coverage.json"

  # Submit coverage data.
  cov-reporter \
    --repository "mozilla-central" \
    --description "site-scout (10k subset)" \
    --tool "site-scout" \
    --submit "./coverage.json"
fi
