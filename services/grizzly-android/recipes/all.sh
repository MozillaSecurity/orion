#!/bin/bash -ex

pip install -r /tmp/recipes/requirements.txt
python /tmp/recipes/emulator.py install avd

chown -R worker:worker /home/worker
