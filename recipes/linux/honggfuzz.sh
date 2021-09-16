#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# supports-test

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Install Honggfuzz

case "${1-install}" in
  install)
    "${0%/*}/llvm.sh"
    sys-embed \
      libbinutils \
      libblocksruntime0 \
      libunwind8
    apt-install-auto \
      binutils-dev \
      git \
      make \
      libblocksruntime-dev \
      libunwind-dev

    TMPD="$(mktemp -d -p. honggfuzz.build.XXXXXXXXXX)"
    pushd "$TMPD" >/dev/null
      git-clone https://github.com/google/honggfuzz
      cd honggfuzz
      git apply <<- EOF
	diff --git a/linux/trace.c b/linux/trace.c
	index 02834637..fdde321a 100644
	--- a/linux/trace.c
	+++ b/linux/trace.c
	@@ -232,8 +232,8 @@ struct user_regs_struct {
	 #endif /* defined(__ANDROID__) */

	 #if defined(__clang__)
	-_Pragma("clang Diagnostic push\n");
	-_Pragma("clang Diagnostic ignored \"-Woverride-init\"\n");
	+_Pragma("clang diagnostic push");
	+_Pragma("clang diagnostic ignored \"-Woverride-init\"");
	 #endif

	 static struct {
	EOF
      CC=clang make
      install honggfuzz /usr/local/bin/
      install hfuzz_cc/hfuzz-cc /usr/local/bin/
      install hfuzz_cc/hfuzz-g* /usr/local/bin/
      install hfuzz_cc/hfuzz-clang* /usr/local/bin/
    popd >/dev/null
    rm -rf "$TMPD"
    ;;
  test)
    honggfuzz --help
    hfuzz-clang --version
    ;;
esac
