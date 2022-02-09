#!/bin/bash
set -e -x

trap 'jobs -p | xargs kill && true' EXIT
export HOME="$PWD"
export NODE_EXTRA_CA_CERTS="$HOMEBREW_PREFIX/share/ca-certificates/cacert.pem"

retry () {
  i=0
  while [ $i -lt 9 ]
  do
    "$@" && return
    sleep 30
    i="${i+1}"
  done
  "$@"
}

status () {
  if [ -n "$TASKCLUSTER_FUZZING_POOL" ]
  then
    python -m TaskStatusReporter --report "$@" || true
  fi
}

export PIP_CONFIG_FILE="$PWD/pip/pip.ini"
python - << EOF
from configparser import ConfigParser

cfg = ConfigParser()
with open("$PIP_CONFIG_FILE", "r+") as fp:
    cfg.read_file(fp)
    cfg["install"]["prefix"] = "$HOMEBREW_PREFIX"
    fp.truncate(0)
    fp.seek(0)
    cfg.write(fp)
EOF

set +x
curl --retry 5 -L "$TASKCLUSTER_PROXY_URL/secrets/v1/secret/project/fuzzing/google-logging-creds" | python -c "import json,sys;json.dump(json.load(sys.stdin)['secret']['key'],open('google_logging_creds.json','w'))"
set -x
cat > td-agent-bit.conf << EOF
[SERVICE]
    Daemon       Off
    Log_File     $PWD/td-agent-bit.log
    Log_Level    info
    Parsers_File $HOMEBREW_PREFIX/etc/fluent-bit/parsers.conf
    Plugins_File $HOMEBREW_PREFIX/etc/fluent-bit/plugins.conf

[INPUT]
    Name tail
    Path $PWD/logs/live.log,$PWD/grizzly-auto-run/screenlog.*
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
    google_service_credentials $PWD/google_logging_creds.json
    resource global

[OUTPUT]
    Name file
    Match screen*.log
    Path $PWD/logs/
    Format template
    Template {time} {message}
EOF
fluent-bit -c td-agent-bit.conf &

# Get fuzzmanager configuration from TC
set +x
curl --retry 5 -L "$TASKCLUSTER_PROXY_URL/secrets/v1/secret/project/fuzzing/fuzzmanagerconf" | python -c "import json,sys;open('.fuzzmanagerconf','w').write(json.load(sys.stdin)['secret']['key'])"
set -x
export FM_CONFIG_PATH="$PWD/.fuzzmanagerconf"

# Update fuzzmanager config for this instance
mkdir -p signatures
cat >> .fuzzmanagerconf << EOF
sigdir = $PWD/signatures
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
curl --retry 5 -L "$TASKCLUSTER_PROXY_URL/secrets/v1/secret/project/fuzzing/deploy-bearspray" | python -c "import json,sys;open('.ssh/id_ecdsa.bearspray','w',newline='\\n').write(json.load(sys.stdin)['secret']['key'])"
set -x
chmod 0600 .ssh/id_ecdsa.bearspray

cat > ssh_wrap.sh << EOF
#!/bin/sh
exec ssh -F '$PWD/.ssh/config' "\$@"
EOF
chmod +x ssh_wrap.sh
export GIT_SSH="$PWD/ssh_wrap.sh"
ssh-keyscan github.com >> .ssh/known_hosts

cat << EOF >> .ssh/config
Host *
UseRoaming no
UserKnownHostsFile $PWD/.ssh/known_hosts

Host bearspray
HostName github.com
IdentitiesOnly yes
IdentityFile $PWD/.ssh/id_ecdsa.bearspray
EOF

# Checkout bearspray
git init bearspray
cd bearspray
git remote add origin git@bearspray:MozillaSecurity/bearspray.git
retry git fetch -q --depth 1 --no-tags origin HEAD
git -c advice.detachedHead=false checkout FETCH_HEAD
cd ..

status "Setup: installing bearspray"
chmod -R +w "$HOMEBREW_PREFIX"
retry python -m pip install --no-build-isolation -e bearspray
python - << EOF
from configparser import ConfigParser

cfg = ConfigParser()
with open("$PIP_CONFIG_FILE", "r+") as fp:
    cfg.read_file(fp)
    del cfg["install"]["prefix"]
    fp.truncate(0)
    fp.seek(0)
    cfg.write(fp)
EOF

status "Setup: launching bearspray"
set +e
bearspray "$ADAPTER"

exit_code=$?
echo "returned $exit_code" >&2
case $exit_code in
  5)  # grizzly.session.Session.EXIT_FAILURE (reduce no-repro)
    exit 0
    ;;
  *)
    exit $exit_code
    ;;
esac
