#!/bin/sh
set -e -x

get-tc-secret google-logging-creds google_logging_creds.json raw
cat > td-agent-bit.conf << EOF
[SERVICE]
    Daemon       On
    Log_File     $USERPROFILE\\td-agent-bit.log
    Log_Level    info
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
    Record host $(relative-hostname)
    Record pool ${EC2SPOTMANAGER_POOLID-${TASKCLUSTER_FUZZING_POOL-unknown}}
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
./td-agent-bit/bin/td-agent-bit -c td-agent-bit.conf

# Get fuzzmanager configuration from TC
get-tc-secret fuzzmanagerconf .fuzzmanagerconf

# Update fuzzmanager config for this instance
mkdir -p signatures
cat >> .fuzzmanagerconf << EOF
sigdir = "$USERPROFILE\\signatures"
tool = bearspray
EOF
setup-fuzzmanager-hostname
chmod 0600 .fuzzmanagerconf

update-ec2-status "Setup: cloning bearspray"

# Get deployment key from TC
mkdir -p .ssh
get-tc-secret deploy-bearspray .ssh/id_ecdsa.bearspray

cat << EOF >> .ssh/config

Host bearspray
HostName github.com
IdentitiesOnly yes
IdentityFile $USERPROFILE\\.ssh\\id_ecdsa.bearspray
EOF

# Checkout bearspray
git-clone git@bearspray:MozillaSecurity/bearspray.git bearspray

update-ec2-status "Setup: installing bearspray"
retry python -m pip install -U -e bearspray

update-ec2-status "Setup: launching bearspray"
python -m bearspray
