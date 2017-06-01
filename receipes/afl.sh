#!/bin/bash -ex

#### AFL

cd $HOME

curl -O http://lcamtuf.coredump.cx/afl/releases/afl-latest.tgz \
  && mkdir afl \
  && tar -xzf afl-latest.tgz -C afl --strip-components=1 \
  && cd afl \
  && make \
  && make install \
  && cd - \
  && rm -f afl-latest.tgz
