#!/bin/sh -ex

#### AFL

cd $HOME

git clone -v --depth 1 https://github.com/choller/afl.git
cd afl
make
# FIXME: https://groups.google.com/forum/#!topic/afl-users/TDLrTu3V_Pw
make -C llvm_mode LLVM_CONFIG=llvm-config-5.0 CC=clang-5.0
make install
cd ..
rm -rf afl
