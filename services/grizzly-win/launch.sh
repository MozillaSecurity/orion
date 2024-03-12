#!/usr/bin/env bash
set -e -x -o pipefail
PATH="$PWD/msys64/opt/node:$PATH"

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

status () {
  if [[ -n "$TASKCLUSTER_FUZZING_POOL" ]]; then
    python -m TaskStatusReporter --report "$@" || true
  fi
}

powershell -ExecutionPolicy Bypass -NoProfile -Command "Set-MpPreference -DisableScriptScanning \$true" || true
powershell -ExecutionPolicy Bypass -NoProfile -Command "Set-MpPreference -DisableRealtimeMonitoring \$true" || true

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
    Path $USERPROFILE\\logs\\live.log,$USERPROFILE\\grizzly-auto-run\\screenlog.*
    Path_Key file
    Key message
    Refresh_Interval 5
    Read_from_Head On
    Skip_Long_Lines On
    Buffer_Max_Size 1M
    DB td-grizzly-logs.pos
    DB.locking true

[FILTER]
    Name rewrite_tag
    Match tail.*
    Rule \$file screenlog.([0-9]+)$ screen\$1.log false
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

[OUTPUT]
    Name file
    Match screen*.log
    Path $USERPROFILE\\logs\\
    Format template
    Template {time} {message}
EOF
./td-agent-bit/bin/fluent-bit.exe -c td-agent-bit.conf &

# ensure we use the latest FM
retry pip install git+https://github.com/MozillaSecurity/FuzzManager

# Get fuzzmanager configuration from TC
set +x
retry-curl "$TASKCLUSTER_PROXY_URL/secrets/v1/secret/project/fuzzing/fuzzmanagerconf" | python -c "import json,sys;open('.fuzzmanagerconf','w').write(json.load(sys.stdin)['secret']['key'])"
set -x

# Update fuzzmanager config for this instance
mkdir -p signatures
cat >> .fuzzmanagerconf << EOF
sigdir = $USERPROFILE\\signatures
tool = bearspray
EOF

# setup-fuzzmanager-hostname
name="task-${TASK_ID}-run-${RUN_ID}"
echo "Using '$name' as hostname." >&2
echo "clientid = $name" >>.fuzzmanagerconf
chmod 0600 .fuzzmanagerconf

status "Setup: cloning bearspray"

# Get deployment key from TC
mkdir -p .ssh
set +x
retry-curl "$TASKCLUSTER_PROXY_URL/secrets/v1/secret/project/fuzzing/deploy-bearspray" | python -c "import json,sys;open('.ssh/id_ecdsa.bearspray','w',newline='\\n').write(json.load(sys.stdin)['secret']['key'])"
set -x

cat << EOF >> .ssh/config

Host bearspray
HostName github.com
IdentitiesOnly yes
IdentityFile $USERPROFILE\\.ssh\\id_ecdsa.bearspray
EOF

if [[ "$ADAPTER" = "reducer" ]]; then
  ssh-keyscan github.com >> .ssh/known_hosts
fi

# Set up Google Cloud Logging creds
if [[ "$ADAPTER" != "reducer" ]]; then
  mkdir -p "$APPDATA/gcloud"
  set +x
  retry-curl "$TASKCLUSTER_PROXY_URL/secrets/v1/secret/project/fuzzing/google-cloud-storage-creds" | python -c "import json,sys;json.dump(json.load(sys.stdin)['secret']['key'],open(r'$APPDATA/gcloud/application_default_credentials.json','w'))"
  set -x
fi

# Checkout bearspray
git init bearspray
cd bearspray
git remote add origin git@bearspray:MozillaSecurity/bearspray.git
retry git fetch -q --depth 1 --no-tags origin HEAD
git -c advice.detachedHead=false checkout FETCH_HEAD
cd ..

status "Setup: installing bearspray"
retry python -m pip install -e bearspray

# Initialize grizzly working directory
mkdir -p AppData/Local/Temp/grizzly

status "Setup: launching bearspray"
set +e
python -m bearspray "$ADAPTER"

exit_code=$?
echo "returned $exit_code" >&2
echo "sleeping so logs can flush" >&2
sleep 15

# Archive grizzly working directory
if [ -d "AppData/Local/Temp/grizzly" ]; then
  7z a -tzip grizzly.zip AppData/Local/Temp/grizzly
fi

case $exit_code in
  5)  # grizzly.session.Session.EXIT_FAILURE (reduce no-repro)
    exit 0
    ;;
  *)
    exit $exit_code
    ;;
esac
