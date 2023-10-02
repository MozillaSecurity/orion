#!/usr/bin/env bash

# resolve current clang toolchain
resolve-toolchain () {
  python3 - <(retry-curl "https://hg.mozilla.org/mozilla-central/raw-file/tip/taskcluster/ci/toolchain/$1.yml") "$1" <<- "EOF"
	import yaml
	import sys
	inp=sys.argv[1]
	name=sys.argv[2]
	with open(inp, "r") as fd:
	  data = yaml.load(fd, Loader=yaml.CLoader)
	for tc, defn in data.items():
	  alias = defn.get("run", {}).get("toolchain-alias", {})
	  if isinstance(alias, dict):
	    alias = alias.get("by-project", {}).get("default")
	  if alias == f"linux64-{name}":
	    print(tc)
	    break
	else:
	  raise Exception(f"No linux64-{name} toolchain found")
	EOF
}

# install clang from firefox-ci
update-ec2-status "[$(date -Iseconds)] setup: installing clang"
CLANG_INDEX="$(resolve-toolchain clang)"
retry-curl "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.cache.level-3.toolchains.v3.$CLANG_INDEX.latest/artifacts/public/build/clang.tar.zst" | zstdcat | tar -x -C /opt
retry-curl "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.cache.level-3.toolchains.v3.${CLANG_INDEX/clang/x64-compiler-rt}.latest/artifacts/public/build/compiler-rt-x86_64-unknown-linux-gnu.tar.zst" | zstdcat | tar --strip-components=1 -C /opt/clang/lib/clang/* -x

retry-curl "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.cache.level-3.content.v1.${CLANG_INDEX/linux64-/}.latest/artifacts/public/llvm-project.tar.zst" | zstdcat | tar -x -O llvm-project/compiler-rt/lib/asan/scripts/asan_symbolize.py > /opt/clang/bin/asan_symbolize
sed -i 's/env python$/env python3/' /opt/clang/bin/asan_symbolize
chmod +x /opt/clang/bin/asan_symbolize

cat << "EOF" >> /etc/profile
PATH="$PATH:/opt/clang/bin"
CC="/opt/clang/bin/clang"
CXX="/opt/clang/bin/clang++"
AR="/opt/clang/bin/llvm-ar"
LDFLAGS="-fuse-ld=lld"
EOF

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
  RUST_INDEX="$(resolve-toolchain rust)"
  retry-curl "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.cache.level-3.toolchains.v3.$RUST_INDEX.latest/artifacts/public/build/rustc.tar.zst" | zstdcat | tar -x -C /opt
  cat << "EOF" >> /etc/profile
PATH="$PATH:/opt/rustc/bin"
EOF
  PATH="$PATH:/opt/rustc/bin"
  rustc --version
  cargo --version
fi
