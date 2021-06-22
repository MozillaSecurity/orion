#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

function retry () {
  op="$(mktemp)"
  for _ in {1..9}; do
    if "$@" >"$op"; then
      cat "$op"
      rm "$op"
      return
    fi
    sleep 30
  done
  rm "$op"
  "$@"
}

function tc-get-secret () {
  TASKCLUSTER_ROOT_URL="${TASKCLUSTER_PROXY_URL-$TASKCLUSTER_ROOT_URL}" retry taskcluster api secrets get "project/fuzzing/$1"
}

# shellcheck source=recipes/linux/common.sh
source $HOME/.local/bin/common.sh

if [[ -z "$NO_SECRETS" ]]
then
  # setup AWS credentials to use S3
  setup-aws-credentials
fi

if [[ -n "$TASK_ID" ]] || [[ -n "$RUN_ID" ]] ; then
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
  TARGET_TIME=$((10 * 365 * 24 * 3600))
fi

# Get the deploy key for fuzzilli from Taskcluster
get-tc-secret deploy-fuzzilli $HOME/.ssh/id_rsa.fuzzilli
get-tc-secret deploy-langfuzz-config $HOME/.ssh/id_rsa.langfuzz-config

# Setup Key Identities
cat << EOF > $HOME/.ssh/config

Host fuzzilli
Hostname github.com
IdentityFile $HOME/.ssh/id_rsa.fuzzilli

Host langfuzz-config
Hostname github.com
IdentityFile $HOME/.ssh/id_rsa.langfuzz-config
EOF

# -----------------------------------------------------------------------------

cd $HOME

git-clone git@langfuzz-config:MozillaSecurity/langfuzz-config.git config
git-clone https://github.com/MozillaSecurity/FuzzManager/

# Checkout the configuration with bootstrap script
git-clone git@fuzzilli:MozillaSecurity/fuzzilli.git fuzzilli

# Copy over the S3Manager, we need it for the fuzzilli daemon
cp FuzzManager/misc/afl-libfuzzer/S3Manager.py fuzzilli/mozilla/

#------- BEGIN BOOTSTRAP

#!/bin/bash
set -e -x

function retry {
  for i in {1..9}; do "$@" && return || sleep 10; done
  "$@"
}

cd $HOME

cp config/fuzzmanagerconf $HOME/.fuzzmanagerconf
if [ -n "$TOOLNAME" ]
then
    sed -i -e "s/tool = Fuzzilli/tool = ${TOOLNAME}/" $HOME/.fuzzmanagerconf
fi
if [ -n "$TASKCLUSTER_ROOT_URL" ] && [ -n "$TASK_ID" ]; then
    echo "clientid = task-${TASK_ID}-run-${RUN_ID}"
elif [ -n "$EC2SPOTMANAGER_POOLID" ]; then
    echo "clientid = $(curl --retry 5 -s http://169.254.169.254/latest/meta-data/public-hostname)"
else
    echo "clientid = ${CLIENT_ID-$(uname -n)}"
fi >> $HOME/.fuzzmanagerconf
chmod 600 $HOME/.fuzzmanagerconf

# Download our build
python3 -mfuzzfetch --central --target js --debug --fuzzilli -n build

cd fuzzilli
chmod +x mozilla/*.sh

source $HOME/.bashrc

echo $PATH
ls -al /opt/swift5

export PATH=/opt/swift5/usr/bin:$PATH

if [[ -n "$S3_CORPUS_REFRESH" ]]
then
  mozilla/merge.sh $HOME/build/dist/bin/js
else
  mozilla/bootstrap.sh
  screen -t fuzzilli -dmSL fuzzilli mozilla/run.sh $HOME/build/dist/bin/js
  mozilla/monitor.sh $HOME/build/dist/bin/js
fi

#------- END BOOTSTRAP



# sleep to keep docker container running
echo "[$(date -u -Iseconds)] waiting ${TARGET_TIME}s"
sleep $TARGET_TIME
echo "[$(date -u -Iseconds)] ${TARGET_TIME}s elapsed, exiting..."
