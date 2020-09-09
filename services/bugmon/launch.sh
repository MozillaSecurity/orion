#!/bin/bash

set -e
set -o pipefail

function retry () {
  for _ in {1..9}; do
    "$@" && return
    sleep 30
  done
  "$@"
}

function tc-get-secret () {
  TASKCLUSTER_ROOT_URL="${TASKCLUSTER_PROXY_URL-$TASKCLUSTER_ROOT_URL}" retry taskcluster api secrets get "project/fuzzing/$1"
}

export ARTIFACT_ROOT="/bugmon-artifacts"

case "$BUGMON_ACTION" in
  monitor | report)
    BZ_API_KEY="$(tc-get-secret bz-api-key | jshon -e secret -e key -u)"
    export BZ_API_KEY
    export BZ_API_ROOT="https://bugzilla.mozilla.org/rest"
    if [ "$BUGMON_ACTION" == "monitor" ]; then
      bugmon-monitor "$ARTIFACT_ROOT"
    else
      bugmon-report "$PROCESSOR_ARTIFACT"
    fi
    ;;
  process)
    bugmon-process "$ARTIFACT_ROOT/$MONITOR_ARTIFACT" "$ARTIFACT_ROOT/$PROCESSOR_ARTIFACT"
    ;;
  *)
    echo "unknown action: $BUGMON_ACTION" >&2
    exit 1
    ;;
esac >"$ARTIFACT_ROOT/live.log" 2>&1
