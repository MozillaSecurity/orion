#!/usr/bin/env -S bash -l
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

COVERAGE="${COVERAGE-0}"

# shellcheck source=recipes/linux/common.sh
source "/srv/repos/setup/common.sh"

# get gcp fuzzdata credentials
mkdir -p ~/.config/gcloud
get-tc-secret google-cloud-storage-guided-fuzzing ~/.config/gcloud/application_default_credentials.json raw

#guided-fuzzing-daemon
for r in fuzzfetch fuzzmanager prefpicker guided-fuzzing-daemon
do
  pushd "/srv/repos/$r" >/dev/null
  retry git fetch origin HEAD
  git reset --hard FETCH_HEAD
  popd >/dev/null
done

update-status () {
  update-ec2-status "[$(date -Is)] $*"
}

get-target-time () {
  if [[ -n "$TASK_ID" ]] || [[ -n "$RUN_ID" ]]
  then
    result=$(($(get-deadline) - $(date +%s) - 5 * 60))
  else
    result=$((10 * 365 * 24 * 3600))
  fi
  if [[ $result -lt $((5 * 60)) ]]
  then
    echo "Not enough time to run!" >&2
    exit 1
  fi
  echo $result
}

# setup AWS credentials to use S3
setup-aws-credentials

# Get FuzzManager configuration
# We require FuzzManager credentials in order to submit our results.
if [[ ! -e ~/.fuzzmanagerconf ]]
then
  get-tc-secret fuzzmanagerconf .fuzzmanagerconf
  # Update FuzzManager config for this instance.
  mkdir -p signatures
  cat >> .fuzzmanagerconf << EOF
sigdir = $HOME/signatures
EOF
  # Update Fuzzmanager config with suitable hostname based on the execution environment.
  setup-fuzzmanager-hostname
  chmod 0600 ~/.fuzzmanagerconf
fi

mkdir -p ~/.ssh
if [[ ! -e ~/.ssh/id_rsa.fuzzing-shells-private ]]
then
  get-tc-secret deploy-fuzzing-shells-private ~/.ssh/id_rsa.fuzzing-shells-private
  cat >> ~/.ssh/config << EOF
Host fuzzing-shells-private github.com
Hostname github.com
IdentityFile ~/.ssh/id_rsa.fuzzing-shells-private
EOF
fi

TOOLNAME="${TOOLNAME:-AFL++-$FUZZER}"
if [[ -n "$JSRT" ]]
then
  if [[ ! -e fuzzing-shells-private ]]
  then
    git-clone git@fuzzing-shells-private:MozillaSecurity/fuzzing-shells-private.git
  fi
  FUZZER="$HOME/fuzzing-shells-private/$JSRT/$FUZZER"
fi

if [[ -n "$TOKENS" ]]
then
  gcs-cat guided-fuzzing-data "$TOKENS" > ./tokens.dict
  TOKENS="./tokens.dict"
fi

# setup target

ASAN_OPTIONS=\
abort_on_error=1:\
hard_rss_limit_mb=4096:\
log_path=/tmp/data.log:\
max_allocation_size_mb=3073:\
strip_path_prefix=/builds/worker/workspace/build/src/:\
symbolize=0:\
$ASAN_OPTIONS
ASAN_OPTIONS=${ASAN_OPTIONS//:/ }

UBSAN_OPTIONS=\
strip_path_prefix=/builds/worker/workspace/build/src/:\
symbolize=0:\
$UBSAN_OPTIONS
UBSAN_OPTIONS=${UBSAN_OPTIONS//:/ }

if [[ "$COVERAGE" = 1 ]]; then
  export ARTIFACT_ROOT="https://community-tc.services.mozilla.com/api/index/v1/task/project.fuzzing.coverage-revision.latest/artifacts/public"
  SOURCE_URL="$(resolve-url "$ARTIFACT_ROOT/source.zip")"
  export SOURCE_URL
  REVISION="$(retry-curl --compressed "$ARTIFACT_ROOT/coverage-revision.txt")"
  export REVISION
fi

TARGET_BIN="$(./setup-target.sh)"

mkdir -p corpus.out

update-status "preparing to launch guided-fuzzing-daemon"

if [[ -n "$TASK_ID" ]] || [[ -n "$RUN_ID" ]]
then
  python3 -m TaskStatusReporter --report-from-file ./stats --keep-reporting 60 --random-offset 30 &

  onexit () {
    # ensure final stats are complete
    if [[ -e ./stats ]]
    then
      python3 -m TaskStatusReporter --report-from-file ./stats
    fi
  }
  trap onexit EXIT
fi

DAEMON_ARGS=(
  --afl-binary-dir /opt/afl-instrumentation/bin
  --afl-timeout "${AFL_TIMEOUT-30000}"
  --afl
  --stats ./stats
  --memory-limit "${MEMORY_LIMIT:-0}"
  "$TARGET_BIN"
)

S3_PROJECT="${S3_PROJECT:-afl-$FUZZER}"
S3_PROJECT_ARGS=(--provider GCS --bucket guided-fuzzing-data --project "$S3_PROJECT")

if [[ -n "$S3_CORPUS_REFRESH" ]]
then
  update-status "starting corpus refresh"
  time xvfb-run guided-fuzzing-daemon "${S3_PROJECT_ARGS[@]}" \
    --corpus-refresh ./corpus \
    "${DAEMON_ARGS[@]}"
else
  if [[ -n "$TASK_ID" ]] || [[ -n "$RUN_ID" ]]
  then
    DAEMON_ARGS+=(--afl-hide-logs)
  fi

  # Sometimes, don't download the existing corpus.
  # This can increase coverage in large targets and prevents bad corpora.
  # Results will be merged with the existing corpus on next refresh.
  if [[ $COVERAGE -eq 1 ]] || [[ $(python3 -c "import random;print(random.randint(1,100))") -le 98 ]]
  then
    # Download the corpus from S3
    update-status "downloading corpus"
    time guided-fuzzing-daemon "${S3_PROJECT_ARGS[@]}" --corpus-download ./corpus
  else
    mkdir -p corpus
  fi
  # Ensure corpus is not empty
  if [[ $(find ./corpus -type f | wc -l) -eq 0 ]]
  then
    echo "Hello world" > ./corpus/input0
  fi

  instance_count="${AFL_INSTANCES:-$(ncpu)}"
  unset AFL_INSTANCES
  export AFL_MAP_SIZE=8388608
  # run and watch for results
  update-status "launching guided-fuzzing-daemon"
  time xvfb-run guided-fuzzing-daemon "${S3_PROJECT_ARGS[@]}" \
    --afl-log-pattern /logs/afl%d.log \
    --fuzzmanager \
    --max-runtime "$(get-target-time)" \
    --afl-async-corpus \
    --instances "$instance_count" \
    --queue-upload \
    --tool "$TOOLNAME" \
    --corpus-in ./corpus \
    --corpus-out ./corpus.out \
    "${DAEMON_ARGS[@]}"
  for st in ./corpus.out/*/fuzzer_stats
  do
    idx="$(basename "$(dirname "$st")")"
    cp "$st" "/logs/fuzzer_stats$idx.txt"
  done
fi

if [[ $COVERAGE -eq 1 ]]
then
  # TODO: coverage.json
  # Submit coverage data.
  python3 -m CovReporter \
    --repository mozilla-central \
    --description "$S3_PROJECT" \
    --tool "$TOOLNAME" \
    --submit ./coverage.json
fi
