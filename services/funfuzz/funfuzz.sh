#!/bin/bash -ex
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

pushd "$HOME"

python3 -u -m funfuzz.loop_bot -b "--random" --target-time 28800 | tee log-loopBotPy.txt

popd
