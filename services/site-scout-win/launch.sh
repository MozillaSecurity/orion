#!/usr/bin/env bash
set -e -x -o pipefail

retry () {
  i=0
  while [[ "$i" -lt 9 ]]; do
    "$@" && return
    sleep 30
    i="$((i+1))"
  done
  "$@"
}
retry-curl () { curl -sSL --connect-timeout 25 --fail --retry 5 -w "%{stderr}[downloaded %{url_effective}]\n" "$@"; }

function get-deadline () {
  if [[ -z "$TASK_ID" ]] || [[ -z "$RUN_ID" ]]; then
    echo "error: get-deadline() is only supported on Taskcluster" >&2
    exit 1
  fi
  tmp="$(mktemp -d)"
  retry-curl "$TASKCLUSTER_ROOT_URL/api/queue/v1/task/$TASK_ID" >"$tmp/task.json"
  retry-curl "$TASKCLUSTER_ROOT_URL/api/queue/v1/task/$TASK_ID/status" >"$tmp/status.json"
  deadline="$(date --date "$(python -c "import json,sys;print(json.load(sys.stdin)['status']['deadline'])" <"$tmp/status.json")" +%s)"
  started="$(date --date "$(python -c "import json,sys;print(json.load(sys.stdin)['status']['runs'][$RUN_ID]['started'])" <"$tmp/status.json")" +%s)"
  max_run_time="$(python -c "import json,sys;print(json.load(sys.stdin)['payload']['maxRunTime'])" <"$tmp/task.json")"
  rm -rf "$tmp"
  run_end="$((started + max_run_time))"
  if [[ $run_end -lt $deadline ]]
  then
    echo "$run_end"
  else
    echo "$deadline"
  fi
}

status () {
  if [[ -n "$TASKCLUSTER_FUZZING_POOL" ]]; then
    task-status-reporter --report "$@" || true
  fi
}

if [[ -n "$TASK_ID" ]] || [[ -n "$RUN_ID" ]]; then
  TARGET_DURATION="$(($(get-deadline) - $(date +%s) - 600))"
  # check if there is enough time to run
  if [[ "$TARGET_DURATION" -le 600 ]]; then
    # create required artifact directory to avoid task failure
    mkdir -p "${TMP}/site-scout"
    status "Not enough time remaining before deadline!"
    exit 0
  fi
  if [[ -n "$RUNTIME_LIMIT" ]] && [[ "$RUNTIME_LIMIT" -lt "$TARGET_DURATION" ]]; then
    TARGET_DURATION="$RUNTIME_LIMIT"
  fi
else
  # RUNTIME_LIMIT or no-limit
  TARGET_DURATION="${RUNTIME_LIMIT-0}"
fi

set +x
retry-curl "$TASKCLUSTER_PROXY_URL/secrets/v1/secret/project/fuzzing/google-logging-creds" | python -c "import json,sys;json.dump(json.load(sys.stdin)['secret']['key'],open('google_logging_creds.json','w'))"
set -x
cat > td-agent-bit.conf << EOF
[SERVICE]
    Daemon       Off
    Log_File     $USERPROFILE\\td-agent-bit.log
    Log_Level    debug
    Parsers_File $USERPROFILE\\td-agent-bit\\conf\\parsers.conf
    Plugins_File $USERPROFILE\\td-agent-bit\\conf\\plugins.conf

[INPUT]
    Name tail
    Path $USERPROFILE\\logs\\live.log
    Path_Key file
    Key message
    Refresh_Interval 5
    Read_from_Head On
    Skip_Long_Lines On
    Buffer_Max_Size 1M
    DB td-grizzly-logs.pos
    DB.locking true

[INPUT]
    Name         winlog
    Channels     Application,System
    Interval_Sec 1

[FILTER]
    Name rewrite_tag
    Match tail.*
    Rule \$file ([^\\\\]+)$ \$1 false

[FILTER]
    Name record_modifier
    Match *
    Record host task-${TASK_ID}-run-${RUN_ID}
    Record pool ${TASKCLUSTER_FUZZING_POOL-unknown}
    Remove_key file

[OUTPUT]
    Name stackdriver
    Match *
    google_service_credentials $USERPROFILE\\google_logging_creds.json
    resource global
EOF
./td-agent-bit/bin/fluent-bit.exe -c td-agent-bit.conf &

# ensure we use the latest FM
retry pip install git+https://github.com/MozillaSecurity/FuzzManager

# Get fuzzmanager configuration from TC
set +x
retry-curl "$TASKCLUSTER_PROXY_URL/secrets/v1/secret/project/fuzzing/fuzzmanagerconf-site-scout" | python -c "import json,sys;open('.fuzzmanagerconf','w').write(json.load(sys.stdin)['secret']['key'])"
set -x

# Update fuzzmanager config for this instance
mkdir -p signatures
cat >> .fuzzmanagerconf << EOF
sigdir = $USERPROFILE\\signatures
EOF

# setup-fuzzmanager-hostname
name="task-${TASK_ID}-run-${RUN_ID}"
echo "Using '$name' as hostname." >&2
echo "clientid = $name" >>.fuzzmanagerconf
chmod 0600 .fuzzmanagerconf

# Install site-scout
status "Setup: installing site-scout"
retry python -m pip install fuzzfetch git+https://github.com/MozillaSecurity/site-scout

# Clone site-scout private
# only clone if it wasn't already mounted via docker run -v
status "Setup: cloning site-scout-private"

# Get deployment key from TC
set +x
retry-curl "$TASKCLUSTER_PROXY_URL/secrets/v1/secret/project/fuzzing/deploy-site-scout-private" | python -c "import json,sys;open('.ssh/id_ecdsa.site-scout-private','w',newline='\\n').write(json.load(sys.stdin)['secret']['key'])"
set -x
cat << EOF >> .ssh/config

Host site-scout-private
HostName github.com
IdentitiesOnly yes
IdentityFile $USERPROFILE\\.ssh\\id_ecdsa.site-scout-private
EOF

# Checkout site-scout-private
git init site-scout-private
cd site-scout-private
git remote add origin git@site-scout-private:MozillaSecurity/site-scout-private.git
retry git fetch -q --depth 1 --no-tags origin HEAD
git -c advice.detachedHead=false checkout FETCH_HEAD
cd ..

status "Setup: fetching build"

# select build
echo "Build types: ${BUILD_TYPES}"
BUILD_SELECT_SCRIPT="import random;print(random.choice(str.split('${BUILD_TYPES}')))"
build="$(python -c "$BUILD_SELECT_SCRIPT")"
# download build
case $build in
  debug32)
    retry fuzzfetch -n build --fuzzing --debug --cpu x86
    ;;
  *)
    retry fuzzfetch -n build --fuzzing "--$build"
    ;;
esac

# setup reporter
echo "No report yet" > status.txt
task-status-reporter --report-from-file status.txt --keep-reporting 60 &
# shellcheck disable=SC2064
trap "kill $!; task-status-reporter --report-from-file status.txt" EXIT

# enable page interactions
if [[ -n "$EXPLORE" ]]; then
  export EXPLORE_FLAG="--explore"
else
  export EXPLORE_FLAG=""
fi

# select URL collections
mkdir active_lists
for LIST in ${URL_LISTS}
do
    cp "./site-scout-private/visit-yml/${LIST}" ./active_lists/
done

# create directory for launch failure results
mkdir -p "${TMP}/site-scout/local-results"

status "Setup: launching site-scout"
site-scout ./build/firefox.exe \
  -i ./active_lists/ \
  $EXPLORE_FLAG \
  --fuzzmanager \
  --jobs "$JOBS" \
  --memory-limit "$MEM_LIMIT" \
  --runtime-limit "$TARGET_DURATION" \
  --status-report status.txt \
  --time-limit "$TIME_LIMIT" \
  --url-limit "${URL_LIMIT-0}" \
  -o "${TMP}/site-scout/local-results"
