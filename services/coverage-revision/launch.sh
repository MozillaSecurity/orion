#!/bin/sh
set -e -x
# store and kill self in pipeline
# this emulates bash -o pipefail
self=$$

DST="${DST-/coverage-revision.txt}"

{ fuzzfetch --coverage --dry-run 2>&1 || kill $self; } | { tee /dev/stderr || kill $self; } | sed -n 's/.*> Changeset: \(.*\)/\1/p' > "$DST"

# Validate that we got a proper revision

## Check that file isn't empty
[ -s "$DST" ]

## Check that the revision exists on mozilla-central
curl -sSIf "https://hg.mozilla.org/mozilla-central/rev/$(cat "$DST")" > /dev/null
