#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# shellcheck source=recipes/linux/taskgraph-m-c-latest.sh
source "$(dirname "${BASH_SOURCE[0]}")/taskgraph-m-c-latest.sh"

# install clang from firefox-ci
update-status "setup: installing clang"
clang_ver="$(resolve-tc-alias clang)"
compiler_ver="x64-compiler-rt-${clang_ver/clang-/}"
retry-curl "$(resolve-tc "$clang_ver")" | zstdcat | tar -x -C /opt
retry-curl "$(resolve-tc "$compiler_ver")" | zstdcat | tar --strip-components=1 -C /opt/clang/lib/clang/* -x
retry-curl "$(resolve-tc-src "$clang_ver")" | zstdcat | tar -x -O llvm-project/compiler-rt/lib/asan/scripts/asan_symbolize.py > /opt/clang/bin/asan_symbolize
sed -i 's/env python$/env python3/' /opt/clang/bin/asan_symbolize
chmod +x /opt/clang/bin/asan_symbolize

if [[ "$SKIP_PROFILE" != "1" ]]; then
  cat << "EOF" >> /etc/profile
PATH="$PATH:/opt/clang/bin"
CC="/opt/clang/bin/clang"
CXX="/opt/clang/bin/clang++"
AR="/opt/clang/bin/llvm-ar"
LDFLAGS="-fuse-ld=lld"
EOF
fi

PATH="$PATH:/opt/clang/bin"
CC="/opt/clang/bin/clang"
CXX="/opt/clang/bin/clang++"
AR="/opt/clang/bin/llvm-ar"
LDFLAGS="-fuse-ld=lld"

export LDFLAGS
export CC
export CXX
export AR
$CC --version

if [[ "$SKIP_RUST" != "1" ]]; then
  # install rust from firefox-ci
  update-status "setup: installing rust"
  retry-curl "$(resolve-tc rust)" | zstdcat | tar -x -C /opt
  if [[ "$SKIP_PROFILE" != "1" ]]; then
    cat << "EOF" >> /etc/profile
PATH="$PATH:/opt/rustc/bin"
EOF
  fi
  PATH="$PATH:/opt/rustc/bin"
  rustc --version
  cargo --version
fi
