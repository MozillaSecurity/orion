#!/usr/bin/env bash
set -e -x -o pipefail
PATH="$PWD/msys64/opt/node:$PATH"

retry() {
  i=0
  while [[ $i -lt 9 ]]; do
    "$@" && return
    sleep 30
    i="$((i + 1))"
  done
  "$@"
}

#shellcheck disable=SC2016
powershell -ExecutionPolicy Bypass -NoProfile -Command 'Set-MpPreference -DisableScriptScanning $true' || echo "failed to disable script scanning"
#shellcheck disable=SC2016
powershell -ExecutionPolicy Bypass -NoProfile -Command 'Set-MpPreference -DisableRealtimeMonitoring $true' || echo "failed to disable RT monitoring"
#shellcheck disable=SC2016
powershell -ExecutionPolicy Bypass -NoProfile -Command 'Disable-WindowsErrorReporting' || echo "failed to disable WER"

mkdir -p "$LOCALAPPDATA/autobisect/autobisect/"
cat <<EOF >"$LOCALAPPDATA/autobisect/autobisect/autobisect.ini"
[autobisect]
storage-path: $(cd "$USERPROFILE" && pwd -W)/builds/
persist: true
; size in MBs
persist-limit: 30000
EOF

retry python -m pip install git+https://github.com/MozillaSecurity/bugmon-tc.git

ARTIFACT_DEST="$PWD/bugmon-artifacts"
TC_ARTIFACT_ROOT="project/fuzzing/bugmon"

CONFIRM_ARGS=""
if [[ -n $FORCE_CONFIRM ]]; then
  CONFIRM_ARGS="--force-confirm"
fi

bugmon-process \
  "$TC_ARTIFACT_ROOT/$MONITOR_ARTIFACT" \
  "$ARTIFACT_DEST/$PROCESSOR_ARTIFACT" \
  $CONFIRM_ARGS >"$ARTIFACT_DEST/live.log" 2>&1
