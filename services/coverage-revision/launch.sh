#!/bin/sh
set -e -x

DST="${DST-/coverage-revision.txt}"

fuzzfetch --coverage --dry-run 2>&1 | tee /dev/stderr | sed -n 's/.*> Changeset: \(.*\)/\1/p' > "$DST"

# Validate that we got a proper revision

## Check that file isn't empty
[ -s "$DST" ]

## Check that the revision exists on mozilla-central
curl -sSIf "https://hg.mozilla.org/mozilla-central/rev/$(cat $DST)" > /dev/null
