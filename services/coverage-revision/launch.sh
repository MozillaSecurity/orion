#!/bin/bash
set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "$HOME/.local/bin/common.sh"

DST="${DST-/coverage-revision.txt}"

CI_LATEST=$(retry-curl --silent https://api.coverage.moz.tools/v2/history | jq -r '.[0].changeset')
if [ -n "$CI_LATEST" ] && fuzzfetch --build "$CI_LATEST" --coverage --fuzzing -a --dry-run 2>&1; then
  echo "$CI_LATEST" > "$DST"
else
  fuzzfetch --coverage --fuzzing -a --dry-run 2>&1 | tee /dev/stderr | sed -n 's/.*> Changeset: \(.*\)/\1/p' > "$DST"
fi

## Check that file isn't empty
[ -s "$DST" ]

## Check that the revision exists on mozilla-central
retry-curl --head "https://hg.mozilla.org/mozilla-central/rev/$(cat "$DST")" > /dev/null
