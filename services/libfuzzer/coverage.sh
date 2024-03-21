#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# shellcheck disable=SC2016
set -e
set -x

# %<---[Setup]----------------------------------------------------------------

WORKDIR=${WORKDIR:-$HOME}
cd "$WORKDIR" || exit

# shellcheck source=recipes/linux/common.sh
source ~/.local/bin/common.sh

# Setup required coverage environment variables.
export COVERAGE=1

export ARTIFACT_ROOT="https://community-tc.services.mozilla.com/api/index/v1/task/project.fuzzing.coverage-revision.latest/artifacts/public"

if [[ -z "$REVISION" ]]; then
  REVISION="$(retry-curl --compressed "$ARTIFACT_ROOT/coverage-revision.txt")"
fi
export REVISION

TOOLNAME="${TOOLNAME:-libFuzzer-$FUZZER}"
if [[ -n "$XPCRT" ]]
then
  TOOLNAME="libFuzzer-xpcrt-$XPCRT"
fi

# Allow overriding some args with coverage specific versions
if [[ -n "$COV_LIBFUZZER_ARGS" ]]
then
  LIBFUZZER_ARGS="$COV_LIBFUZZER_ARGS"
  export LIBFUZZER_ARGS
fi

if [[ -n "$COV_LIBFUZZER_INSTANCES" ]]
then
  LIBFUZZER_INSTANCES="$COV_LIBFUZZER_INSTANCES"
  export LIBFUZZER_INSTANCES
fi

# Our default target is Firefox, but we support targeting the JS engine instead.
# In either case, we check if the target is already mounted into the container.
# For coverage, we also are pinned to a given revision and we need to fetch coverage builds.
TARGET_BIN="$(./setup-target.sh)"
JS="${JS:-0}"
if [[ "$JS" = "1" ]] || [[ -n "$JSRT" ]]
then
  export GCOV_PREFIX="$HOME/js"
else
  export GCOV_PREFIX="$HOME/firefox"
fi

GCOV_PREFIX_STRIP="$(grep pathprefix "$HOME/${TARGET_BIN}.fuzzmanagerconf" | grep -E -o "/.+$" | tr -cd '/' | wc -c)"
export GCOV_PREFIX_STRIP

# %<---[LibFuzzer]------------------------------------------------------------

timeout --foreground -s 2 -k $((COVRUNTIME + 60)) "$COVRUNTIME" ./libfuzzer.sh || :

# %<---[Coverage]-------------------------------------------------------------

retry-curl --compressed -O "$ARTIFACT_ROOT/source.zip"
unzip source.zip

# Collect coverage count data.
RUST_BACKTRACE=1 grcov "$GCOV_PREFIX" \
    -t coveralls+ \
    --commit-sha "$REVISION" \
    --token NONE \
    --guess-directory-when-missing \
    --ignore-not-existing \
    -p "$(rg -Nor '$1' "pathprefix = (.*)" "$HOME/${TARGET_BIN}.fuzzmanagerconf")" \
    -s "./${REPO-mozilla-central}-$REVISION" \
    > "$WORKDIR/coverage.json"

# Submit coverage data.
python3 -m CovReporter \
    --repository "${REPO-mozilla-central}" \
    --description "libFuzzer ($FUZZER,rt=$COVRUNTIME)" \
    --tool "$TOOLNAME" \
    --submit "$WORKDIR/coverage.json"
