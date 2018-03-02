#!/bin/bash -ex

#### MiniDumpStackWalk

# - Linux64
curl -L https://api.pub.build.mozilla.org/tooltool/sha512/76d704f0bfa110f5ea298b87200e34ec09d039b9d1a59ec819fc8e02b2cf073af32a4536dca33a3813f037a557fd0669b48a063c7a920f6308b307148029d41f -o /usr/local/bin/minidump_stackwalk
# - Linux32
# curl -L https://api.pub.build.mozilla.org/tooltool/sha512/70cf423b4cc04c2a7bdb50b802e2528d517c5c5192cd94b729e7b07fc5e943c709bed2357287b5388a5332b7be31b13a0d334fded6ae7c36c12ceda1710b901a -o /usr/local/bin/minidump_stackwalk
chmod a+x /usr/local/bin/minidump_stackwalk
