#!/usr/bin/env -S bash -l
set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "/srv/repos/setup/common.sh"

# start logging
get-tc-secret google-logging-creds /etc/google/auth/application_default_credentials.json raw
mkdir -p /etc/td-agent-bit
cat > /etc/td-agent-bit/td-agent-bit.conf << EOF
[SERVICE]
    Daemon       On
    Log_File     /var/log/td-agent-bit.log
    Log_Level    info
    Parsers_File parsers.conf
    Plugins_File plugins.conf

[INPUT]
    Name tail
    Path /logs/live.log
    Path_Key file
    Key message
    Refresh_Interval 5
    Read_from_Head On
    Skip_Long_Lines On
    Buffer_Max_Size 1M
    DB /var/lib/td-agent-bit/pos/grizzly-logs.pos
    DB.locking true

[FILTER]
    Name rewrite_tag
    Match tail.*
    Rule \$file screenlog.([0-9]+)$ screen\$1.log false
    Rule \$file ([^/]+)$ \$1 false

[FILTER]
    Name record_modifier
    Match *
    Record host $(relative-hostname)
    Record pool ${EC2SPOTMANAGER_POOLID-${TASKCLUSTER_FUZZING_POOL-unknown}}
    Remove_key file

[OUTPUT]
    Name stackdriver
    Match *
    google_service_credentials /etc/google/auth/application_default_credentials.json
    resource global

[OUTPUT]
    Name file
    Match screen*.log
    Path /logs/
    Format template
    Template {time} {message}
EOF
mkdir -p /var/lib/td-agent-bit/pos
/opt/td-agent-bit/bin/td-agent-bit -c /etc/td-agent-bit/td-agent-bit.conf

# install clang
export SKIP_RUST=1
source "/srv/repos/setup/clang.sh"
retry-curl "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.cache.level-3.toolchains.v3.sysroot-x86_64-linux-gnu.latest/artifacts/public/build/sysroot-x86_64-linux-gnu.tar.zst" | zstdcat | tar -x -C /opt

# setup kvm device
kvm_gid="$(stat -c%g /dev/kvm)"
kvm_grp="$(grep ":$kvm_gid:" /etc/group | cut -d: -f1)"
if [[ ! -e /dev/kvm ]]; then
  mknod /dev/kvm c 10 "$(grep '\<kvm\>' /proc/misc | cut -f 1 -d' ')"
fi
usermod -a -G "$kvm_grp" worker

# shellcheck disable=SC2317
function onexit () {
  echo "Waiting for logs to flush..." >&2
  sleep 15
  killall -INT td-agent-bit || true
  sleep 15
}
trap onexit EXIT

chown -R worker:worker /home/worker/sharedir
su worker -c "/home/worker/launch-worker.sh"
