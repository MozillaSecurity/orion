#!/usr/bin/env bash
set -e
mkdir -p /logs
"./launch-root.sh" >/logs/live.log 2>&1
