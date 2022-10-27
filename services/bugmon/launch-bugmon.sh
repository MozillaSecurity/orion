#!/bin/bash
set -x
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

# shellcheck source=recipes/linux/common.sh
source ~/.local/bin/common.sh

if [[ -v FORCE_CONFIRM ]]; then
  FORCE_CONFIRM="--force-confirm"
fi

export PATH=$PATH:/home/worker/.local/bin
export ARTIFACT_DEST="/bugmon-artifacts"
export TC_ARTIFACT_ROOT="project/fuzzing/bugmon"

curl -sSL https://install.python-poetry.org | python3 -
git-clone https://github.com/MozillaSecurity/bugmon-tc.git ./bugmon-tc
cd bugmon-tc
poetry install

# Copy pernosco-shared to poetry python virtual env
BASE_PY_PATH="$(python3 -c 'import distutils.sysconfig;print(distutils.sysconfig.get_python_lib())')"
POETRY_PY_PATH="$(poetry run python3 -c 'import distutils.sysconfig;print(distutils.sysconfig.get_python_lib())')"
cp -r "$BASE_PY_PATH/pernoscoshared" "$POETRY_PY_PATH"

# Initialize the grizzly directory to avoid TC errors
mkdir -p /tmp/grizzly

TRACE_ARGS=()
if [ -v TRACE_ARTIFACT ]; then
  TRACE_ARGS+=("--trace-artifact" "$ARTIFACT_DEST/$TRACE_ARTIFACT")
fi

set +x
case "$BUG_ACTION" in
  monitor | report)
    BZ_API_KEY="$(tc-get-secret bz-api-key | jshon -e secret -e key -u)"
    export BZ_API_KEY
    export BZ_API_ROOT="https://bugzilla.mozilla.org/rest"
    if [ "$BUG_ACTION" == "monitor" ]; then
      set -x
      poetry run bugmon-monitor "$ARTIFACT_DEST" $FORCE_CONFIRM
      set +x
    else
      PERNOSCO_USER="$(tc-get-secret pernosco-user | jshon -e secret -e key -u)"
      PERNOSCO_GROUP="$(tc-get-secret pernosco-group | jshon -e secret -e key -u)"
      PERNOSCO_USER_SECRET_KEY="$(tc-get-secret pernosco-secret | jshon -e secret -e key -u)"
      export PERNOSCO_USER PERNOSCO_GROUP PERNOSCO_USER_SECRET_KEY
      set -x
      poetry run bugmon-report "$TC_ARTIFACT_ROOT/$PROCESSOR_ARTIFACT" "${TRACE_ARGS[@]}"
      set +x
    fi
    ;;
  process)
    set -x
    poetry run bugmon-process \
      "$TC_ARTIFACT_ROOT/$MONITOR_ARTIFACT" \
      "$ARTIFACT_DEST/$PROCESSOR_ARTIFACT" \
      "${TRACE_ARGS[@]}" \
      $FORCE_CONFIRM
    set +x
    ;;
  *)
    echo "unknown action: $BUG_ACTION" >&2
    exit 1
    ;;
esac >"$ARTIFACT_DEST/live.log" 2>&1
