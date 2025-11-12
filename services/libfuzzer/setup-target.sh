#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# %<---[Setup]----------------------------------------------------------------

# shellcheck source=recipes/linux/common.sh
source ~/.local/bin/common.sh

# %<---[Target]---------------------------------------------------------------

FETCH_ARGS=(-o "$HOME" --fuzzing)

if [[ -n $JSRT ]] && [[ -z $COVERAGE ]]; then
  FETCH_ARGS+=(--debug)
else
  FETCH_ARGS+=(--asan)
fi

FETCH_ARGS+=(--cpu "${CPU_ARCH:-$(uname -m)}")

if [[ $COVERAGE == 1 ]]; then
  FETCH_ARGS+=(--coverage --build "$REVISION")
fi

if [[ $REPO == "try" ]]; then
  FETCH_ARGS+=(--try)
fi

# Our default target is Firefox, the JS engine and Thunderbird are also supported.
# In either case, we check if the target is already mounted into the container.
JS="${JS:-0}"
THUNDERBIRD="${THUNDERBIRD:-0}"
if [[ $JS == 1 ]] || [[ -n $JSRT ]]; then
  if [[ ! -d "$HOME/js" ]]; then
    retry fuzzfetch -n js --target js "${FETCH_ARGS[@]}"
  fi
  if [[ -n $JSRT ]]; then
    TARGET_BIN="js/dist/bin/js"
  else
    # if we are using the fuzz-tests target, copy fuzzmanagerconf from the js binary
    cp "$HOME/js/dist/bin/js.fuzzmanagerconf" "$HOME/js/dist/bin/fuzz-tests.fuzzmanagerconf"
    TARGET_BIN="js/dist/bin/fuzz-tests"
  fi
elif [[ $THUNDERBIRD == 1 ]]; then
  TARGET_BIN="thunderbird/thunderbird"
  if [[ ! -d "$HOME/thunderbird" ]]; then
    FETCH_ARGS+=(--target thunderbird gtest)
    retry fuzzfetch -n thunderbird "${FETCH_ARGS[@]}"
  fi
else
  TARGET_BIN="firefox/firefox"
  if [[ ! -d "$HOME/firefox" ]]; then
    FETCH_ARGS+=(--target firefox common gtest xpcshell)
    retry fuzzfetch -n firefox "${FETCH_ARGS[@]}"
  fi
fi
echo "$TARGET_BIN"
