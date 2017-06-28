#!/bin/sh -ex

#### AFL

cd $HOME

git clone -v --depth 1 https://github.com/choller/afl.git
cd afl
make
cd llvm_mode
make
cd ..
make install
cd ..
rm -rf afl
