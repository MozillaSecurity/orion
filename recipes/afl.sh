#!/bin/sh -ex

#### AFL

cd "$HOME"

git clone -v --depth 1 --no-tags https://github.com/choller/afl.git
( cd afl
  make
  make -C llvm_mode
  make install
)
rm -rf afl
