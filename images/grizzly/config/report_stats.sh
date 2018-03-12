#!/bin/bash -x

while true; do
  ~/config/merge_status.py ~/grizzly ~/stats && python -m EC2Reporter.EC2Reporter --report-from-file ~/stats
  sleep 60
done
