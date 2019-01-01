#!/bin/bash -ex

pushd "$HOME"

cat << EOF >> .bashrc

ulimit -c unlimited

ccache -M 12G
EOF

popd
