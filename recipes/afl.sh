#!/bin/sh -ex

#### AFL

cd "$HOME"

git clone -v --depth 1 https://github.com/choller/afl.git
( cd afl
  make
  make -C llvm_mode
  make install
)
rm -rf afl
