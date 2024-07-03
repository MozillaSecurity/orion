#!/bin/bash
set -x
set -e
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source ~/.local/bin/common.sh

CONFIRM_ARGS=()
if [[ -v FORCE_CONFIRM ]]; then
  CONFIRM_ARGS+=("--force-confirm")
fi

export PATH=$PATH:/home/worker/.local/bin
export ARTIFACT_DEST="/bugmon-artifacts"
export TC_ARTIFACT_ROOT="project/fuzzing/bugmon"

retry-curl https://install.python-poetry.org | python3 - --version 1.7.0
git-clone https://github.com/MozillaSecurity/bugmon-tc.git ./bugmon-tc
cd bugmon-tc
poetry install

mkdir -p /home/worker/.cache/autobisect
mkdir -p /home/worker/.config/autobisect
cat << EOF >  /home/worker/.config/autobisect/autobisect.ini
[autobisect]
storage-path: /home/worker/.cache/autobisect
persist: false
; size in MBs
persist-limit: 0
EOF

# Copy pernosco-shared to poetry python virtual env
BASE_PY_PATH="$(python3 -c 'import distutils.sysconfig;print(distutils.sysconfig.get_python_lib())')"
POETRY_PY_PATH="$(poetry run python3 -c 'import distutils.sysconfig;print(distutils.sysconfig.get_python_lib())')"
cp -r "$BASE_PY_PATH/pernoscoshared" "$POETRY_PY_PATH"

# Initialize the grizzly directory to avoid TC errors
mkdir -p /tmp/grizzly

set +x

case "$BUG_ACTION" in
  monitor | report)
    BZ_API_KEY="$(get-tc-secret bz-api-key)"
    export BZ_API_KEY
    export BZ_API_ROOT="https://bugzilla.mozilla.org/rest"
    if [ "$BUG_ACTION" == "monitor" ]; then
      poetry run bugmon-monitor "$ARTIFACT_DEST" "${CONFIRM_ARGS[@]}"
    else
      PERNOSCO_USER="$(get-tc-secret pernosco-user)"
      PERNOSCO_GROUP="$(get-tc-secret pernosco-group)"
      PERNOSCO_USER_SECRET_KEY="$(get-tc-secret pernosco-secret)"
      export PERNOSCO_USER PERNOSCO_GROUP PERNOSCO_USER_SECRET_KEY

      TRACE_ARGS=()
      if [ -v TRACE_ARTIFACT ]; then
        TRACE_ARGS+=("--trace-artifact" "$TC_ARTIFACT_ROOT/$TRACE_ARTIFACT")
      fi
      poetry run bugmon-report "$TC_ARTIFACT_ROOT/$PROCESSOR_ARTIFACT" "${TRACE_ARGS[@]}"
    fi
    ;;
  process)
    TRACE_ARGS=()
    if [ -v TRACE_ARTIFACT ]; then
      TRACE_ARGS+=("--trace-artifact" "$ARTIFACT_DEST/$TRACE_ARTIFACT")
    fi

    poetry run bugmon-process \
      "$TC_ARTIFACT_ROOT/$MONITOR_ARTIFACT" \
      "$ARTIFACT_DEST/$PROCESSOR_ARTIFACT" \
      "${TRACE_ARGS[@]}" \
      "${CONFIRM_ARGS[@]}"
    ;;
  *)
    echo "unknown action: $BUG_ACTION" >&2
    exit 1
    ;;
esac >"$ARTIFACT_DEST/live.log" 2>&1
