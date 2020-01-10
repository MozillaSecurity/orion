#!/bin/bash -ex
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

pushd "$HOME"

# Populate Mercurial settings.
cat << EOF > .hgrc
[ui]
username = funfuzz
merge = internal:merge
ssh = ssh -C -v

[extensions]
mq =
progress =
purge =
rebase =
EOF

popd
