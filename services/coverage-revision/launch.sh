#!/bin/sh
set -e -x
# store and kill self in pipeline
# this emulates bash -o pipefail
self=$$

DST="${DST-/coverage-revision.txt}"

{ fuzzfetch --coverage --fuzzing -a --dry-run 2>&1 || kill $self; } | { tee /dev/stderr || kill $self; } | sed -n 's/.*> Changeset: \(.*\)/\1/p' > "$DST"

# Validate that we got a proper revision

## Check that file isn't empty
[ -s "$DST" ]

## Download revision source so coverage tasks can fetch from here
retry_curl () { curl -sSL --connect-timeout 25 --fail --retry 12 -w "%{stderr}[downloaded %{url_effective}]\n" "$@"; }
retry_curl "https://hg.mozilla.org/mozilla-central/archive/$(cat "$DST").zip" -o /source.zip
