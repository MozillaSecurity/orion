#!/bin/bash
set -x

# Required for pernosco
sysctl -w kernel.perf_event_paranoid=1

su worker -c /home/worker/launch-bugmon.sh
