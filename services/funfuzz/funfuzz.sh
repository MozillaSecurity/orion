#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source ~/.local/bin/common.sh

if [[ ! -e ~/.fuzzmanagerconf ]] && [[ -z "$NO_SECRETS" ]]
then
  get-tc-secret fuzzmanagerconf ~/.fuzzmanagerconf
  setup-fuzzmanager-hostname
  chmod 0600 ~/.fuzzmanagerconf
fi
# don't use `Collector --refresh` because make_collector sets tool and sigdir
python3 -c "from funfuzz.util import create_collector; create_collector.make_collector().refresh()"

JS_SHELL_DEFAULT_TIMEOUT=24
export GCOV=/usr/local/bin/gcov-9

if [[ -n "$EC2SPOTMANAGER_CYCLETIME" ]]
then
  TARGET_TIME="$EC2SPOTMANAGER_CYCLETIME"
elif [[ -n "$TASK_ID" ]]
then
  function get-deadline () {
    tmp="$(mktemp -d)"
    retry taskcluster api queue task "$TASK_ID" >"$tmp/task.json"
    retry taskcluster api queue status "$TASK_ID" >"$tmp/status.json"
    deadline="$(date --date "$(jshon -e status -e deadline -u <"$tmp/status.json")" +%s)"
    started="$(date --date "$(jshon -e status -e runs -e "$RUN_ID" -e started -u <"$tmp/status.json")" +%s)"
    max_run_time="$(jshon -e payload -e maxRunTime -u <"$tmp/task.json")"
    rm -rf "$tmp"
    run_end="$((started + max_run_time))"
    if [[ $run_end -lt $deadline ]]; then
      echo "$run_end"
    else
      echo "$deadline"
    fi
  }
  TARGET_TIME="$(($(get-deadline) - $(date +%s) - 5 * 60))"
else
  TARGET_TIME=28800
fi

if [[ -z "$COVERAGE" ]]
then
mode_args=()
case "${MODE-default}" in
  "wasm")
    ;;
  "compare-jit")
    mode_args+=("--no-fuzz-wasm" "--compare-jit")
    ;;
  "default")
    mode_args+=("--no-fuzz-wasm")
    ;;
  *)
    echo "warning: unknown value for \$MODE: $MODE, assuming 'default'" >&2
    mode_args+=("--no-fuzz-wasm")
    ;;
esac
fi

if [[ -z "$NO_PULL" ]]
then
  (cd ~/trees/funfuzz
   retry git fetch --depth 1 origin master
   git reset --hard FETCH_HEAD
  )
fi

BUILDS="$HOME/builds"
mkdir -p "$BUILDS"

if [[ -z "$COVERAGE" ]]
then
builds=(
  mc-32-debug
  mc-32-debug
  mc-32-opt
  mc-64-debug
  mc-64-debug
  mc-64-debug
  mc-64-debug
  mc-64-opt
  mc-64-opt
  mc-64-opt-asan
  mc-64-opt-asan
)
function select-build () {
  while true; do
    n="$(python3 -c "import random;print(random.randrange(${#builds[@]}))")"
    build="${builds[n]}"
    if [[ ! -d "$BUILDS/$build" ]]
    then
      flags=(--central --target js -o "$BUILDS" -n "$build")
      case "$build" in
        mc-32-debug)
          flags+=(--debug --cpu x86)
          ;;
        mc-32-opt)
          flags+=(--cpu x86)
          ;;
        mc-64-debug)
          flags+=(--debug)
          ;;
        mc-64-opt)
          ;;
        mc-64-opt-asan)
          flags+=(--asan)
          ;;
        *)
          echo "unknown build: $build" >&2
          exit 1
          ;;
      esac
      if python3 -m fuzzfetch "${flags[@]}"; then
        break
      else
        echo "failed to download $build! ... picking again in 10s" >&2
        sleep 10
      fi
    else
      break
    fi
  done
  echo "$build"
}
fi

screen -d -m -L -S funfuzz
if [[ -z "$COVERAGE" ]]
then
  nprocs="${NPROCS-$(python3 -c "import os;print(len(os.sched_getaffinity(0)))")}"
  update-ec2-status "$(echo -e "About to start fuzzing $nprocs\n  with target time $TARGET_TIME\n  and jsfunfuzz timeout of $JS_SHELL_DEFAULT_TIMEOUT ...")" || true
else
  nprocs="${NPROCS-1}"
  update-ec2-status "$(echo -e "About to start coverage $nprocs\n  with target time $TARGET_TIME ...")" || true
fi
echo "[$(date)] launching $nprocs processes..."
for (( i=1; i<=nprocs; i++ ))
do
  if [[ -z "$COVERAGE" ]]
  then
    build="$(select-build)"
    screen -S funfuzz -X setenv LD_LIBRARY_PATH "$BUILDS/$build/dist/bin/"
    screen -S funfuzz -X screen python3 -u -m funfuzz.js.loop --repo=none --random-flags "${mode_args[@]}" "$JS_SHELL_DEFAULT_TIMEOUT" "" "$BUILDS/$build/dist/bin/js"
  else
    screen -S funfuzz -X screen python3 -u -m funfuzz.run_ccoverage --report --target-time="$((TARGET_TIME - 5 * 60))"
  fi
  sleep 1
done
screen -S funfuzz -X screen ~/status.sh
echo "[$(date -u -Iseconds)] waiting $TARGET_TIME"
sleep "$TARGET_TIME"
echo "[$(date -u -Iseconds)] $TARGET_TIME elapsed, exiting..."
