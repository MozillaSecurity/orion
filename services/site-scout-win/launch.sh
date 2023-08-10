#!/bin/sh
set -e -x

retry () {
  i=0
  while [ "$i" -lt 9 ]
  do
    "$@" && return
    sleep 30
    i="$((i+1))"
  done
  "$@"
}
retry_curl () { curl -sSL --connect-timeout 25 --fail --retry 5 "$@"; }

status () {
  if [ -n "$TASKCLUSTER_FUZZING_POOL" ]
  then
    python -m TaskStatusReporter --report "$@" || true
  fi
}

set +x
retry_curl "$TASKCLUSTER_PROXY_URL/secrets/v1/secret/project/fuzzing/google-logging-creds" | python -c "import json,sys;json.dump(json.load(sys.stdin)['secret']['key'],open('google_logging_creds.json','w'))"
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
retry_curl "$TASKCLUSTER_PROXY_URL/secrets/v1/secret/project/fuzzing/fuzzmanagerconf-site-scout" | python -c "import json,sys;open('.fuzzmanagerconf','w').write(json.load(sys.stdin)['secret']['key'])"
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
retry python -m pip install --user --no-build-isolation fuzzfetch git+https://github.com/MozillaSecurity/site-scout

# Clone site-scout private
# only clone if it wasn't already mounted via docker run -v
status "Setup: cloning site-scout-private"

# Get deployment key from TC
get-tc-secret deploy-site-scout-private .ssh/id_ecdsa.site-scout-private
set +x
retry_curl "$TASKCLUSTER_PROXY_URL/secrets/v1/secret/project/fuzzing/deploy-site-scout-private" | python -c "import json,sys;open('.ssh/id_ecdsa.site-scout-private','w',newline='\\n').write(json.load(sys.stdin)['secret']['key'])"
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
build="$(python -c "import random;print(random.choice(['asan','debug','debug32']))")"
case $build in
  debug32)
    fuzzfetch -n build --fuzzing --debug --cpu x86
    ;;
  *)
    fuzzfetch -n build --fuzzing "--$build"
    ;;
esac

# setup reporter
python -m TaskStatusReporter --report-from-file status.txt --keep-reporting 60 &
# shellcheck disable=SC2064
trap "kill $!" EXIT

status "Setup: launching site-scout"
yml="$(python -c "import pathlib,random;print(random.choice(list(pathlib.Path('site-scout-private').glob('**/*.yml'))))")"
site-scout ./build/firefox -i "$yml" --status-report status.txt --time-limit 60 --jobs 2 --fuzzmanager
