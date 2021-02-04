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

export ARTIFACT_DEST="/bugmon-artifacts"
export TC_ARTIFACT_ROOT="project/fuzzing/bugmon"

git init bugmon-tc
(
  cd bugmon-tc
  git remote add -t master origin https://github.com/MozillaSecurity/bugmon-tc.git
  retry git fetch -v --depth 1 --no-tags origin master
  git reset --hard FETCH_HEAD
  pip3 install .
)

case "$BUG_ACTION" in
  monitor | report)
    BZ_API_KEY="$(tc-get-secret bz-api-key | jshon -e secret -e key -u)"
    export BZ_API_KEY
    export BZ_API_ROOT="https://bugzilla.mozilla.org/rest"
    if [ "$BUG_ACTION" == "monitor" ]; then
      bugmon-monitor "$ARTIFACT_DEST"
    else
      bugmon-report "$TC_ARTIFACT_ROOT/$PROCESSOR_ARTIFACT"
    fi
    ;;
  process)
    bugmon-process "$TC_ARTIFACT_ROOT/$MONITOR_ARTIFACT" "$ARTIFACT_DEST/$PROCESSOR_ARTIFACT" --dry-run
    ;;
  *)
    echo "unknown action: $BUG_ACTION" >&2
    exit 1
    ;;
esac >"$ARTIFACT_DEST/live.log" 2>&1
