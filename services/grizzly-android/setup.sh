#!/bin/bash -ex
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=recipes/linux/common.sh
source ~worker/.local/bin/common.sh

CLANG_SRC="clang/lib/clang/*"

sys-update
sys-embed qemu-kvm
apt-install-auto zstd

(
  cd /tmp
  curl --retry 5 -L https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.cache.level-3.toolchains.v3.linux64-clang-14.latest/artifacts/public/build/clang.tar.zst -o /tmp/clang.tar.zst
  zstdcat /tmp/clang.tar.zst | tar --wildcards -x "${CLANG_SRC}/lib/linux/"
  rm /tmp/clang.tar.zst

  # shellcheck disable=SC2086
  CLANG_SRC="$(ls -d ${CLANG_SRC})"  # don't quote CLANG_SRC! need to expand wildcard
  CLANG_VERSION="$(basename "${CLANG_SRC}")"
  CLANG_DEST="android-ndk/toolchains/llvm/prebuilt/linux-x86_64/lib64/clang/${CLANG_VERSION}"

  mkdir -p ~worker/"${CLANG_DEST}/lib/linux"
  cp "${CLANG_SRC}/lib/linux/libclang_rt.asan-x86_64-android.so" ~worker/"${CLANG_DEST}/lib/linux/libclang_rt.asan-x86_64-android.so"
  cp "${CLANG_SRC}/lib/linux/libclang_rt.asan-i686-android.so" ~worker/"${CLANG_DEST}/lib/linux/libclang_rt.asan-i686-android.so"
  rm -rf clang
)

pip3 install /src/emulator_install
su worker -c "emulator-install --no-launch"

~worker/.local/bin/cleanup.sh

chown -R worker:worker /home/worker
usermod -a -G kvm worker
