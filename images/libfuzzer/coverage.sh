#!/bin/bash -xu
# shellcheck disable=SC2016

# %<---[setup]----------------------------------------------------------------

WORKDIR=${WORKDIR:-$HOME}
cd "$WORKDIR" || exit

# Fetch a Firefox coverage build and its coverage notes files plus gtest.
# We might have a volume attached which mounts a build into the container.
if [[ ! -d "$WORKDIR/firefox" ]]
then
    #python -m fuzzfetch --coverage --tests gtest -n firefox -o "$WORKDIR"
    python -m fuzzfetch \
        --build gecko.v2.mozilla-central.latest.firefox.linux64-fuzzing-asan-opt-cov \
        --tests gtest \
        -n firefox \
        -o "$WORKDIR"
    chmod -R 755 firefox
    (cd firefox \
    && curl -LO https://index.taskcluster.net/v1/task/gecko.v2.mozilla-central.latest.firefox.linux64-fuzzing-asan-opt-cov/artifacts/public/build/target.code-coverage-gcno.zip \
    && unzip target.code-coverage-gcno.zip)
fi

# Download mozilla-central source code.
# We might have a volume attached which mounts the source into the container.
REVISION=$(rg -Nor '$1' "SourceStamp=(.*)" "$WORKDIR/firefox/platform.ini")
if [[ ! -d "$WORKDIR/mozilla-central" ]]
then
    export REVISION
    hg clone -r "$REVISION" https://hg.mozilla.org/mozilla-central
else
    (cd mozilla-central && hg update -r "$REVISION")
fi

# Setup required coverage environment variables.
export COVERAGE=1
export GCOV_PREFIX_STRIP=6
export GCOV_PREFIX="$WORKDIR/firefox"

# %<---[fuzzer]---------------------------------------------------------------

timeout --foreground -s 2 -k $((COVRUNTIME + 30)) "$COVRUNTIME" ./libfuzzer.sh

# %<---[coverage]-------------------------------------------------------------

# Collect coverage count data.
grcov "$WORKDIR/firefox" \
    --llvm \
    -t coveralls+ \
    --commit-sha "$REVISION" \
    --token NONE \
    -s "$WORKDIR/mozilla-central" \
    -p "$(rg -Nor '$1' "pathprefix = (.*)" "$WORKDIR/firefox/firefox.fuzzmanagerconf")" \
    > "$WORKDIR/coverage.json"

# Submit coverage data.
python -m CovReporter.CovReporter \
    --repository mozilla-central \
    --description "FuzzOS-LibFuzzer ($FUZZER,rt=$COVRUNTIME)" \
    --tool "FuzzOS-LibFuzzer-$FUZZER" \
    --submit "$WORKDIR/coverage.json"

# Disable our pool.
if [[ $EC2SPOTMANAGER_POOLID ]]
then
    python -m EC2Reporter --disable "$EC2SPOTMANAGER_POOLID"
fi
