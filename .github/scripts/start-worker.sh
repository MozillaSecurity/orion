#!/bin/sh -e

[ -n "$TASKCLUSTER_ACCESS_TOKEN" ] || {
  echo "Missing TASKCLUSTER_ACCESS_TOKEN" >&2
  exit 2
}
[ -n "$TC_WORKER_ID" ] || {
  echo "Missing TC_WORKER_ID" >&2
  exit 2
}
[ -n "$ORION_GITHUB_TOKEN_FILE" ] || {
  echo "Missing ORION_GITHUB_TOKEN_FILE" >&2
  exit 2
}
[ -f "$ORION_GITHUB_TOKEN_FILE" ] || {
  echo "Missing protected GitHub token file" >&2
  exit 2
}
[ "$(stat -c '%a' "$ORION_GITHUB_TOKEN_FILE")" = 600 ] || {
  echo "GitHub token file must have mode 0600" >&2
  exit 2
}

TC_PROJECT=fuzzing
TC_WORKER_TYPE=orion-gha-publish
TC_IDLE_TIMEOUT=300
TASKCLUSTER_ROOT_URL="https://community-tc.services.mozilla.com"
TASKCLUSTER_CLIENT_ID="project/$TC_PROJECT/worker-$TC_WORKER_TYPE-gh"

# generic-worker logs its complete process environment. The allowlist leaves it
# only the token-file path; raw GitHub and Taskcluster credentials never enter it.
set +x
cat >worker.config <<EOF
{
  "accessToken": "$TASKCLUSTER_ACCESS_TOKEN",
  "clientId": "$TASKCLUSTER_CLIENT_ID",
  "disableReboots": true,
  "headlessTasks": true,
  "ed25519SigningKeyLocation": "worker.key",
  "idleTimeoutSecs": $TC_IDLE_TIMEOUT,
  "livelogExecutable": "$PWD/livelog",
  "provisionerId": "proj-$TC_PROJECT",
  "publicIP": "127.0.0.1",
  "requiredDiskSpaceMegabytes": 512,
  "rootURL": "$TASKCLUSTER_ROOT_URL",
  "sentryProject": "generic-worker",
  "taskclusterProxyExecutable": "$PWD/taskcluster-proxy",
  "taskclusterProxyPort": 8080,
  "tasksDir": "tasks",
  "workerGroup": "proj-$TC_PROJECT",
  "workerId": "$TC_WORKER_ID",
  "workerType": "$TC_WORKER_TYPE",
  "wstAudience": "communitytc",
  "wstServerURL": "https://community-websocktunnel.services.mozilla.com"
}
EOF
chmod 0600 worker.config
unset TASKCLUSTER_ACCESS_TOKEN

retry_curl() {
  curl --connect-timeout 25 --fail --retry 5 --show-error --silent "$@"
}

TC_VERSION="$(retry_curl --head "https://github.com/taskcluster/taskcluster/releases/latest" | sed -n 's#.*tag/\([^[:space:]]*\).*#\1#p' | tr -d '\r')"
[ -n "$TC_VERSION" ] || {
  echo "Could not resolve Taskcluster release" >&2
  exit 2
}
retry_curl -L "https://github.com/taskcluster/taskcluster/releases/download/$TC_VERSION/generic-worker-insecure-linux-amd64" -o generic-worker
retry_curl -L "https://github.com/taskcluster/taskcluster/releases/download/$TC_VERSION/livelog-linux-amd64" -o livelog
retry_curl -L "https://github.com/taskcluster/taskcluster/releases/download/$TC_VERSION/taskcluster-proxy-linux-amd64" -o taskcluster-proxy
chmod 0755 generic-worker livelog taskcluster-proxy

./generic-worker new-ed25519-keypair --file worker.key
mkdir -p tasks
set +e
env -i \
  HOME="$HOME" \
  PATH="$PATH" \
  TMPDIR="${TMPDIR:-/tmp}" \
  RUNNER_TEMP="$RUNNER_TEMP" \
  ORION_GITHUB_TOKEN_FILE="$ORION_GITHUB_TOKEN_FILE" \
  ./generic-worker run --config worker.config &
worker_pid=$!
# shellcheck disable=SC2329 # Called indirectly by the signal trap.
stop_worker() {
  kill -TERM "$worker_pid" 2>/dev/null
  wait "$worker_pid"
  exit 143
}
trap stop_worker TERM INT HUP
wait "$worker_pid"
status=$?
trap - TERM INT HUP
set -e
case "$status" in
  0 | 68) exit 0 ;;
  *) exit "$status" ;;
esac
