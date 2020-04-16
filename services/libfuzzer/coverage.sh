#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# shellcheck disable=SC2016,SC2046
set -e
set -x

# %<---[Setup]----------------------------------------------------------------

WORKDIR=${WORKDIR:-$HOME}
cd "$WORKDIR" || exit

# shellcheck source=recipes/linux/common.sh
source ~/.local/bin/common.sh

REVISION=$(curl -sL https://build.fuzzing.mozilla.org/builds/coverage-revision.txt)
export REVISION

# Our default target is Firefox, but we support targetting the JS engine instead.
# In either case, we check if the target is already mounted into the container.
# For coverage, we also are pinned to a given revision and we need to fetch coverage builds.
TARGET_BIN="firefox/firefox"
export JS=${JS:-0}
if [ "$JS" = 1 ]
then
  if [[ ! -d "$HOME/js" ]]
  then
    retry fuzzfetch --build "$REVISION" --asan --coverage --fuzzing --tests gtest -n js -o "$WORKDIR" --target js
  fi
  chmod -R 755 js
  TARGET_BIN="js/fuzz-tests"
  export GCOV_PREFIX="$WORKDIR/js"
elif [[ ! -d "$HOME/firefox" ]]
then
  retry fuzzfetch --build "$REVISION" --asan --coverage --fuzzing --tests gtest -n firefox -o "$WORKDIR"
  chmod -R 755 firefox
  export GCOV_PREFIX="$WORKDIR/firefox"
fi

# Setup required coverage environment variables.
export COVERAGE=1

GCOV_PREFIX_STRIP=$(grep pathprefix "$WORKDIR/${TARGET_BIN}.fuzzmanagerconf" | grep -E -o "/.+$" | tr -cd '/' | wc -c)
export GCOV_PREFIX_STRIP

# %<---[LibFuzzer]------------------------------------------------------------

timeout -s 2 -k $((COVRUNTIME + 60)) "$COVRUNTIME" ./libfuzzer.sh || :

# %<---[Coverage]-------------------------------------------------------------

# Collect coverage count data.
RUST_BACKTRACE=1 grcov "$GCOV_PREFIX" \
    -t coveralls+ \
    --commit-sha "$REVISION" \
    --token NONE \
    --guess-directory-when-missing \
    -p $(rg -Nor '$1' "pathprefix = (.*)" "$WORKDIR/${TARGET_BIN}.fuzzmanagerconf") \
    > "$WORKDIR/coverage.json"

# Submit coverage data.
python3 -m CovReporter \
    --repository mozilla-central \
    --description "libFuzzer ($FUZZER,rt=$COVRUNTIME)" \
    --tool "libFuzzer-$FUZZER" \
    --submit "$WORKDIR/coverage.json"
