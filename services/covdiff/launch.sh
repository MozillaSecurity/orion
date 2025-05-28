#!/bin/bash

set -e
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "$HOME/.local/bin/common.sh"

set -x

export CI=1
export EMAIL=nobody@community-tc.services.mozilla.com

get-tc-secret moz-ci-coverage-key "$HOME/moz-ci-coverage-key.json" raw
get-tc-secret fuzzmanagerconf "$HOME/.fuzzmanagerconf"

REVISION="$(retry-curl --compressed https://community-tc.services.mozilla.com/api/index/v1/task/project.fuzzing.coverage-revision.latest/artifacts/public/coverage-revision.txt)"

TEST_SUITE=(
  mochitest-plain
  mochitest-plain-gpu
  mochitest-webgl1-core
  mochitest-webgl1-ext
  mochitest-webgl2-core
  mochitest-webgl2-core
  web-platform-tests
)

git config --global init.defaultBranch main
git init covdiff
(
  cd covdiff
  git remote add origin https://github.com/MozillaSecurity/covdiff.git
  retry git fetch -q --depth=10 origin main
  git -c advice.detachedHead=false checkout origin/main
  poetry install
  ARGS=(
    "$HOME/moz-ci-coverage-key.json"
    "$REVISION"
    "$HOME/report.json"
    --suite "${TEST_SUITE[@]}"
    --platform "linux"
  )

  poetry run python -m covdiff.fetch "${ARGS[@]}"
  if [ -f "$HOME/report.json" ]; then
    COV_ARGS=(
      --preprocessed
      --branch "central"
      --description "IGNORE_MERGE"
      --repository "mozilla-central"
      --revision "$REVISION"
      --tool "covdiff"
      --submit "$HOME/report.json"
    )
    cov-reporter "${COV_ARGS[@]}"
  fi
) >/live.log 2>&1
