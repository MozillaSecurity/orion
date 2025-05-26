#!/bin/bash
set -e
set -x
set -o pipefail

sed -nE 's/^\s*"(--.*)",/\1/p' "$HOME/fuzzilli/Sources/FuzzilliCli/Profiles/SpidermonkeyProfile.swift" | read -ar flags

if [[ -n $DIFFERENTIAL ]]; then
  flags+=(--differential-testing)
fi

GCOV_PREFIX_STRIP=$(grep pathprefix "$1.fuzzmanagerconf" | grep -E -o "/.+$" | tr -cd '/' | wc -c)
export GCOV_PREFIX_STRIP
export GCOV_PREFIX="$2"

find "$HOME/results/corpus" -name "*.js" | while read -r f; do
  timeout 10 "$1" "${flags[@]}" "$f" || true
done

REV=$(grep product_version "$1.fuzzmanagerconf" | cut -d '=' -f 2 | cut -d '-' -f 2 | tr -d '[:space:]')
COVPREFIX=$(grep pathprefix "$1.fuzzmanagerconf" | grep -E -o "/.+$")

# Generate coverage
grcov "$2" --guess-directory-when-missing -t coveralls+ --commit-sha "$REV" --token NONE -p "$COVPREFIX" >/home/ubuntu/coverage.json

# Submit coverage
cov-reporter --repository mozilla-central --description "JS Engine ($TARGET,rt=$COVRUNTIME)$EXP" --tool fuzzilli --submit /home/ubuntu/coverage.json
