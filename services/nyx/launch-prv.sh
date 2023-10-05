#!/usr/bin/env bash
set -e
mkdir -p /logs
if [[ -n "$TASK_ID" ]] || [[ -n "$RUN_ID" ]]; then
  exec "./launch-root.sh" >/logs/live.log 2>&1
else
  exec "./launch-root.sh"
fi
