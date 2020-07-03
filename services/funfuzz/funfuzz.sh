#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source ~/.local/bin/common.sh

retry credstash get fuzzmanagerconf > ~/.fuzzmanagerconf
chmod 0600 ~/.fuzzmanagerconf
setup-fuzzmanager-hostname "$SHIP"

JS_SHELL_DEFAULT_TIMEOUT=24

if [[ -n "$EC2SPOTMANAGER_CYCLETIME" ]]
then
  TARGET_TIME="$EC2SPOTMANAGER_CYCLETIME"
elif [[ -n "$TASK_ID" ]]
then
  deadline="$(taskcluster api queue status "$TASK_ID" | jshon -e status -e deadline -u)"
  TARGET_TIME="$(python3 -c "import datetime,dateutil;print(int((dateutil.parser.isoparse('$deadline')-datetime.datetime.now()).total_seconds()))")"
else
  TARGET_TIME=28800
fi

(cd ~/trees/funfuzz
 retry git fetch --depth 1 origin master
 git reset --hard FETCH_HEAD
)

BUILDS="$HOME/builds"
mkdir -p "$BUILDS"

builds=(asan debug)
function select-build () {
  n="$(python3 -c "import random;print(random.randrange(${#builds[@]}))")"
  build="${builds[n]}"
  if [[ ! -d "$BUILDS/$build" ]]
  then
    case "$build" in
      asan)
        fuzzfetch --target js -o "$BUILDS" --asan --fuzzing -n "$build"
        ;;
      debug)
        fuzzfetch --target js -o "$BUILDS" --debug --fuzzing -n "$build"
        ;;
      *)
        echo "unknown build: $build" >&2
        exit 1
        ;;
    esac
  fi
  echo "$build"
}

screen -d -m -L -S funfuzz
nprocs="$(python3 -c "import multiprocessing;print(multiprocessing.cpu_count())")"
update-ec2-status "$(echo -e "About to start fuzzing $nprocs\n  with target time $TARGET_TIME\n  and jsfunfuzz timeout of $JS_SHELL_DEFAULT_TIMEOUT ...")"
echo "[$(date)] launching $nprocs processes..."
for (( i=1; i<=nprocs; i++ ))
do
  build="$(select-build)"
  screen -S funfuzz -X screen python3 -u -m funfuzz.js.loop --repo=none --random-flags "$JS_SHELL_DEFAULT_TIMEOUT" "" "$BUILDS/$build/dist/bin/js"
done
echo "[$(date)] waiting $TARGET_TIME"
sleep $TARGET_TIME
echo "[$(date)] $TARGET_TIME elapsed, exiting..."
