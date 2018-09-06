#!/bin/bash -ex

python /tmp/recipes/emulator.py install avd

chown -R worker:worker /home/worker
