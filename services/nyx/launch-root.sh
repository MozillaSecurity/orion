#!/usr/bin/env -S bash -l
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "/srv/repos/setup/common.sh"

# start logging
get-tc-secret google-logging-creds /etc/google/auth/application_default_credentials.json raw
mkdir -p /etc/td-agent-bit /logs
cat > /etc/td-agent-bit/td-agent-bit.conf << EOF
[SERVICE]
    Daemon       On
    Log_File     /var/log/td-agent-bit.log
    Log_Level    info
    Parsers_File parsers.conf
    Plugins_File plugins.conf

[INPUT]
    Name tail
    Path /logs/live.log,/logs/nyx*.log,/logs/afl*.log
    Path_Key file
    Key message
    Refresh_Interval 5
    Read_from_Head On
    Skip_Long_Lines On
    Buffer_Max_Size 1M
    DB /var/lib/td-agent-bit/pos/nyx.pos
    DB.locking true

[FILTER]
    Name rewrite_tag
    Match tail.*
    Rule \$file ([^/]+)$ \$1 false

[FILTER]
    Name record_modifier
    Match *
    Record host $(relative-hostname)
    Record pool ${TASKCLUSTER_FUZZING_POOL-unknown}
    Remove_key file

[OUTPUT]
    Name stackdriver
    Match *
    google_service_credentials /etc/google/auth/application_default_credentials.json
    resource global
EOF
mkdir -p /var/lib/td-agent-bit/pos
/opt/td-agent-bit/bin/td-agent-bit -c /etc/td-agent-bit/td-agent-bit.conf

# install clang
export SKIP_RUST=1
source "/srv/repos/setup/clang.sh"
retry-curl "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.cache.level-3.toolchains.v3.sysroot-x86_64-linux-gnu.latest/artifacts/public/build/sysroot-x86_64-linux-gnu.tar.zst" | zstdcat | tar -x -C /opt

# setup kvm device
kvm_gid="$(stat -c%g /dev/kvm)"
kvm_grp="$({ grep ":$kvm_gid:" /etc/group || true; } | cut -d: -f1)"
if [[ -z "$kvm_grp" ]]; then
  groupadd -g "$kvm_gid" --system kvm
  kvm_grp=kvm
fi
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
chown root:worker /logs
chmod 0775 /logs
su worker -c "/home/worker/launch-worker.sh"
