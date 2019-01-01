#!/bin/bash -ex

pushd "$HOME"

python3 -u -m funfuzz.loop_bot -b "--random" --target-time 28800 | tee log-loopBotPy.txt

popd
