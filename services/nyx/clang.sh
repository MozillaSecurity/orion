#!/usr/bin/env bash

# shellcheck source=recipes/linux/taskgraph-m-c-latest.sh
source "$(dirname "${BASH_SOURCE[0]}")/taskgraph-m-c-latest.sh"

# install clang from firefox-ci
update-ec2-status "[$(date -Iseconds)] setup: installing clang"
retry-curl "$(resolve-tc clang)" | zstdcat | tar -x -C /opt
clang_ver="$(resolve-tc-alias clang)"
compiler_ver="x64-compiler-rt-${clang_ver/clang-/}"
compiler_task="$(resolve-tc "$compiler_ver")"
compiler_task="${compiler_task/\/public\/*/}/$(resolve-tc-artifact compiler-rt "$compiler_ver")"
retry-curl "$compiler_task" | zstdcat | tar --strip-components=1 -C /opt/clang/lib/clang/* -x
retry-curl "$(resolve-tc-src clang)" | zstdcat | tar -x -O llvm-project/compiler-rt/lib/asan/scripts/asan_symbolize.py > /opt/clang/bin/asan_symbolize
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
  update-ec2-status "[$(date -Iseconds)] setup: installing rust"
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
