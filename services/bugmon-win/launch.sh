#!/bin/sh
set -e -x
PATH="$PWD/msys64/opt/node:$PATH"

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
retry_curl () { curl -sSL --connect-timeout 25 --fail --retry 5 -w "%{stderr}[downloaded %{url_effective}]\n" "$@"; }

powershell -ExecutionPolicy Bypass -NoProfile -Command "Set-MpPreference -DisableScriptScanning \$true" || true
powershell -ExecutionPolicy Bypass -NoProfile -Command "Set-MpPreference -DisableRealtimeMonitoring \$true" || true

retry python -m pip install git+https://github.com/MozillaSecurity/bugmon-tc.git

ARTIFACT_DEST="$USERPROFILE/bugmon-artifacts"
TC_ARTIFACT_ROOT="$USERPROFILE/project/fuzzing/bugmon"

CONFIRM_ARGS=""
if [ -n "$FORCE_CONFIRM" ]; then
  CONFIRM_ARGS="--force-confirm"
fi

bugmon-process \
  "$TC_ARTIFACT_ROOT/$MONITOR_ARTIFACT" \
  "$ARTIFACT_DEST/$PROCESSOR_ARTIFACT" \
  $CONFIRM_ARGS >"$ARTIFACT_DEST/live.log" 2>&1