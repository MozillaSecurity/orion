#!/bin/bash -ex

pushd "$HOME"

cat << EOF >> .bashrc

ulimit -c unlimited

# Expand bash shell history length
export HISTTIMEFORMAT="%h %d %H:%M:%S "
HISTSIZE=10000

# Modify bash prompt
export PS1="[\u@\h \d \t \W ] $ "

export LD_LIBRARY_PATH=.
export ASAN_SYMBOLIZER_PATH=/usr/bin/llvm-symbolizer

PATH=/home/worker/.cargo/bin:/home/worker/.local/bin:$PATH

ccache -M 12G
EOF

popd
