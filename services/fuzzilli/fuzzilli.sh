#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# disable core dumps
ulimit -c 0

# shellcheck source=recipes/linux/common.sh
source "$HOME/.local/bin/common.sh"

if [[ -z "$NO_SECRETS" ]]
then
  # setup AWS credentials to use S3
  setup-aws-credentials
fi

if [[ -n "$TASK_ID" ]] || [[ -n "$RUN_ID" ]]
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
    if [[ $run_end -lt $deadline ]]
    then
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
if [[ $DIFFERENTIAL ]]
then
  get-tc-secret deploy-fuzzilli-differential "$HOME/.ssh/id_rsa.fuzzilli"

  # Setup Key Identities for private fuzzilli fork
  cat << EOF > "$HOME/.ssh/config"

Host fuzzilli
Hostname github.com
IdentityFile "$HOME/.ssh/id_rsa.fuzzilli"
EOF

else
  get-tc-secret deploy-fuzzing-shells-private ~/.ssh/id_rsa.fuzzing-shells-private

  # Setup Key Identities for private overlay
  cat >> ~/.ssh/config << EOF

Host fuzzing-shells-private
Hostname github.com
IdentityFile "$HOME/.ssh/id_rsa.fuzzing-shells-private"
EOF

fi

# -----------------------------------------------------------------------------

cd "$HOME"

git-clone https://github.com/MozillaSecurity/FuzzManager/

# Download our build
if [[ $DIFFERENTIAL ]]
then
  git-clone git@fuzzilli:MozillaSecurity/fuzzilli-differential.git fuzzilli
else
  git-clone https://github.com/googleprojectzero/fuzzilli fuzzilli
  git-clone git@fuzzing-shells-private:MozillaSecurity/fuzzing-shells-private.git

  rsync -rv --progress fuzzing-shells-private/fuzzilli/ fuzzilli/
fi

# Copy over the S3Manager, we need it for the fuzzilli daemon
cp FuzzManager/misc/afl-libfuzzer/S3Manager.py fuzzilli/mozilla/

get-tc-secret fuzzmanagerconf "$HOME/.fuzzmanagerconf"
cat >> "$HOME/.fuzzmanagerconf" << EOF
sigdir = $HOME/signatures
tool = ${TOOLNAME-Fuzzilli}
EOF

if [[ -n "$TASKCLUSTER_ROOT_URL" ]] && [[ -n "$TASK_ID" ]]
then
    echo "clientid = task-${TASK_ID}-run-${RUN_ID}"
elif [[ -n "$EC2SPOTMANAGER_POOLID" ]]
then
    echo "clientid = $(retry-curl http://169.254.169.254/latest/meta-data/public-hostname)"
else
    echo "clientid = ${CLIENT_ID-$(uname -n)}"
fi >> "$HOME/.fuzzmanagerconf"

# Download our build
if [[ $COVERAGE ]]
then
  retry python3 -m fuzzfetch --central --target js --coverage -n build
else
  retry python3 -m fuzzfetch --central --target js --debug --fuzzilli -n build
fi

cd fuzzilli
chmod +x mozilla/*.sh

source "$HOME/.bashrc"

echo "$PATH"
ls -al /opt/swift5

export PATH=/opt/swift5/usr/bin:$PATH

if [[ -n "$TASK_ID" ]] || [[ -n "$RUN_ID" ]]
then
  python3 -m TaskStatusReporter --report-from-file ./stats --keep-reporting 60 --random-offset 30 &

  onexit () {
    # ensure final stats are complete
    if [[ -e ./stats ]]
    then
      python3 -m TaskStatusReporter --report-from-file ./stats
    fi
  }
  trap onexit EXIT
fi

if [[ -n "$S3_CORPUS_REFRESH" ]]
then
  timeout -s 2 ${TARGET_TIME} mozilla/merge.sh "$HOME/build/dist/bin/js"
elif [[ $COVERAGE ]]
then
  mozilla/bootstrap.sh
  timeout -s 2 ${TARGET_TIME} mozilla/coverage.sh "$HOME/build/dist/bin/js" "$HOME/build/"
else
  mozilla/bootstrap.sh
  screen -t fuzzilli -dmSL fuzzilli mozilla/run.sh "$HOME/build/dist/bin/js"
  timeout -s 2 ${TARGET_TIME} mozilla/monitor.sh "$HOME/build/dist/bin/js" || [[ $? -eq 124 ]]
fi
