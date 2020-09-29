#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source ~/.local/bin/common.sh

if [[ ! -e ~/.fuzzmanagerconf ]] && [[ -z "$NO_CREDSTASH" ]]
then
  retry credstash get fuzzmanagerconf > ~/.fuzzmanagerconf
  setup-fuzzmanager-hostname "$SHIP"
  chmod 0600 ~/.fuzzmanagerconf
fi

JS_SHELL_DEFAULT_TIMEOUT=24

if [[ -n "$EC2SPOTMANAGER_CYCLETIME" ]]
then
  TARGET_TIME="$EC2SPOTMANAGER_CYCLETIME"
elif [[ -n "$TASK_ID" ]]
then
  deadline="$(taskcluster api queue status "$TASK_ID" | jshon -e status -e deadline -u)"
  TARGET_TIME="$(python3 -c "import datetime,dateutil.parser;print(int((dateutil.parser.isoparse('$deadline')-datetime.datetime.now(datetime.timezone.utc)).total_seconds())-5*60)")"
else
  TARGET_TIME=28800
fi

(cd ~/trees/funfuzz
 retry git fetch --depth 1 origin master
 git reset --hard FETCH_HEAD
)

BUILDS="$HOME/builds"
mkdir -p "$BUILDS"

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
      if fuzzfetch "${flags[@]}"; then
        break
      else
        echo "failed to download $build! ... picking again in 10s" >&2
        sleep 10
      fi
    fi
  done
  echo "$build"
}

screen -d -m -L -S funfuzz
nprocs="${NPROCS-$(python3 -c "import multiprocessing;print(multiprocessing.cpu_count())")}"
update-ec2-status "$(echo -e "About to start fuzzing $nprocs\n  with target time $TARGET_TIME\n  and jsfunfuzz timeout of $JS_SHELL_DEFAULT_TIMEOUT ...")" || true
echo "[$(date)] launching $nprocs processes..."
for (( i=1; i<=nprocs; i++ ))
do
  build="$(select-build)"
  screen -S funfuzz -X setenv LD_LIBRARY_PATH "$BUILDS/$build/dist/bin/"
  screen -S funfuzz -X screen python3 -u -m funfuzz.js.loop --repo=none --random-flags "$JS_SHELL_DEFAULT_TIMEOUT" "" "$BUILDS/$build/dist/bin/js"
  sleep 1
done
screen -S funfuzz -X screen ~/status.sh
echo "[$(date)] waiting $TARGET_TIME"
sleep $TARGET_TIME
echo "[$(date)] $TARGET_TIME elapsed, exiting..."
