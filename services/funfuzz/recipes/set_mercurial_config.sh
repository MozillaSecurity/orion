#!/bin/bash -ex

pushd "$HOME"

# Populate Mercurial settings.
cat << EOF > .hgrc
[ui]
merge = internal:merge
ssh = ssh -C -v

[extensions]
mq =
progress =
purge =
rebase =
EOF

popd
