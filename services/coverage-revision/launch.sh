#!/usr/bin/env bash
set -e -x -o pipefail

DST="${DST-/coverage-revision.txt}"

retry fuzzfetch --coverage --fuzzing -a --dry-run 2>&1 | tee /dev/stderr | sed -n 's/.*> Changeset: \(.*\)/\1/p' > "$DST"

# Validate that we got a proper revision

## Check that file isn't empty
[[ -s "$DST" ]]

## Download revision source so coverage tasks can fetch from here
retry-curl () { curl -sSL --connect-timeout 25 --fail --retry 12 -w "%{stderr}[downloaded %{url_effective}]\n" "$@"; }
retry-curl "https://hg.mozilla.org/mozilla-central/archive/$(cat "$DST").zip" -o /source.zip
