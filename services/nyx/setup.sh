#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

# Fix some packages
# ref: https://github.com/moby/moby/issues/1024
dpkg-divert --local --rename --add /sbin/initctl
ln -sf /bin/true /sbin/initctl

DEBIAN_FRONTEND="teletype"
export DEBIAN_FRONTEND

# Add unprivileged user
useradd --create-home --home-dir /home/worker --shell /bin/bash worker

pkgs=(
  ca-certificates
  curl
  gcc
  git
  jshon
  lbzip2
  libasound2
  libblocksruntime0
  libfontconfig1
  libfreetype6
  libglib2.0-0
  libgtk-3-0
  libjpeg-turbo8
  libpixman-1-0
  libpng16-16
  libx11-6
  libx11-xcb1
  libxcomposite1
  libxdamage1
  libxext6
  libxfixes3
  libxml2
  libxrandr2
  make
  netcat-openbsd
  openssh-client
  psmisc
  python3-dev
  python3-minimal
  xvfb
  zstd
)

sys-update
apt-install-auto libblocksruntime-dev make
sys-embed "${pkgs[@]}"
retry-curl https://bootstrap.pypa.io/get-pip.py | python3 -

mkdir -p /root/.ssh /home/worker/.ssh /home/worker/.local/bin
retry ssh-keyscan github.com | tee -a /root/.ssh/known_hosts /home/worker/.ssh/known_hosts > /dev/null

SRCDIR=/srv/repos/fuzzing-decision "${0%/*}/fuzzing_tc.sh"
"${0%/*}/fluentbit.sh"
"${0%/*}/taskcluster.sh"
export SKIP_PROFILE=1
source "${0%/*}/clang.sh"

function git-clone-rev () {
  local dest rev url
  url="$1"
  rev="$2"
  if [[ $# -eq 3 ]]
  then
    dest="$3"
  else
    dest="$(basename "$1" .git)"
  fi
  git init "$dest"
  pushd "$dest" >/dev/null || return 1
  git remote add origin "$url"
  retry git fetch -q --depth 1 --no-tags origin "$rev"
  git -c advice.detachedHead=false checkout "$rev"
  popd >/dev/null || return 1
}

# build AFL++ w/ Nyx
apt-install-auto libgtk-3-dev pax-utils python3-msgpack python3-jinja2 cpio bzip2
pushd /srv/repos >/dev/null
git-clone-rev https://github.com/AFLplusplus/AFLplusplus 36db3428ab16156dd72196213d2a02a5eadaed11
pushd AFLplusplus >/dev/null
# WIP 2-byte chunked variant of honggfuzz custom mutator
retry-curl https://github.com/AFLplusplus/AFLplusplus/commit/1b611bb30c14724f0f2eb9330772d30723ba122c.diff | git apply
# llvm 19 fixes
retry-curl https://github.com/AFLplusplus/AFLplusplus/commit/a6e42d98d9d3e936dc74729f17ab1208d477c944.diff | git apply
# Collect persistent coverage data and dump it at the end of the run
retry-curl https://github.com/AFLplusplus/AFLplusplus/commit/8fcca6fb410a6ece1a4cd2eb8a2cdeed4d4d9865.diff | git apply
# Fix for afl-showmap/cmin
retry-curl https://github.com/AFLplusplus/AFLplusplus/commit/c5acf3f137733b341b7337d7da47a5545943b457.diff | git apply
git apply << "EOF"
diff --git a/custom_mutators/honggfuzz/Makefile b/custom_mutators/honggfuzz/Makefile
index 5c2fcddb..2dde8ba1 100644
--- a/custom_mutators/honggfuzz/Makefile
+++ b/custom_mutators/honggfuzz/Makefile
@@ -1,5 +1,5 @@

-CFLAGS = -O3 -funroll-loops -fPIC -Wl,-Bsymbolic
+CFLAGS = -O3 -funroll-loops -fPIC -fblocks -lBlocksRuntime -Wl,-Bsymbolic

 all: honggfuzz-mutator.so honggfuzz-2b-chunked-mutator.so

commit d606e18332b4f919780604b9daf9a3761602b7c5
Author: Jesse Schwartzentruber <truber@mozilla.com>
Date:   Fri Jul 14 11:04:04 2023 -0400

    Increase MAP_SIZE for Nyx

diff --git a/include/config.h b/include/config.h
index 8585041e..6e526717 100644
--- a/include/config.h
+++ b/include/config.h
@@ -442,7 +442,7 @@
    problems with complex programs). You need to recompile the target binary
    after changing this - otherwise, SEGVs may ensue. */

-#define MAP_SIZE_POW2 16
+#define MAP_SIZE_POW2 23

 /* Do not change this unless you really know what you are doing. */

EOF
make -f GNUmakefile afl-fuzz afl-showmap CODE_COVERAGE=1
pushd custom_mutators/honggfuzz >/dev/null
make
popd >/dev/null
pushd nyx_mode >/dev/null
git submodule init
retry git submodule update --depth 1 --single-branch libnyx
pushd libnyx >/dev/null
git apply << "EOF"
diff --git a/fuzz_runner/src/nyx/qemu_process.rs b/fuzz_runner/src/nyx/qemu_process.rs
index d062d87..c4ebeea 100644
--- a/fuzz_runner/src/nyx/qemu_process.rs
+++ b/fuzz_runner/src/nyx/qemu_process.rs
@@ -97,9 +97,7 @@ impl QemuProcess {
     pub fn new(params: QemuParams) -> Result<QemuProcess, String> {
         Self::prepare_redqueen_workdir(&params.workdir, params.qemu_id);

-        if params.qemu_id == 0{
-            println!("[!] libnyx: spawning qemu with:\n {}", params.cmd.join(" "));
-        }
+        println!("[!] libnyx: spawning qemu with:\n {}", params.cmd.join(" "));

         let (shm_work_dir, file_lock) = Self::create_shm_work_dir();
         let mut shm_work_dir_path = PathBuf::from(&shm_work_dir);
EOF
popd >/dev/null
retry git submodule update --depth 1 --single-branch packer
retry git submodule update --depth 1 --single-branch QEMU-Nyx
pushd QEMU-Nyx >/dev/null
git submodule init
retry git submodule update --depth 1 --single-branch capstone_v4
retry git submodule update --depth 1 --single-branch libxdc
export CAPSTONE_ROOT="$PWD/capstone_v4"
export LIBXDC_ROOT="$PWD/libxdc"
sed -i '/^LDFLAGS =$/d' libxdc/Makefile
git apply << "EOF"
diff --git a/nyx/hypercall/hypercall.c b/nyx/hypercall/hypercall.c
index fa06af3201..47053472ed 100644
--- a/nyx/hypercall/hypercall.c
+++ b/nyx/hypercall/hypercall.c
@@ -746,9 +746,34 @@ static void handle_hypercall_kafl_dump_file(struct kvm_run *run,
         strncpy(filename, "tmp.XXXXXX", sizeof(filename) - 1);
     }

-    char *base_name = basename(filename); // clobbers the filename buffer!
-    assert(asprintf(&host_path, "%s/dump/%s", GET_GLOBAL_STATE()->workdir_path,
-                    base_name) != -1);
+    char *slashmatch = strstr(filename, "/");
+    char *base_name = NULL;
+    if (slashmatch) {
+        char sub_dir[256];
+        memset(sub_dir, 0, sizeof(sub_dir));
+        memcpy(sub_dir, filename, slashmatch - filename);
+
+        // Safety check, avoid dots in the subdir as they might make us
+        // leave the dump directory.
+        if (strstr(sub_dir, ".") || !strlen(sub_dir)) {
+            nyx_error("Invalid filename in %s: %s. Skipping..\n",
+                      __func__, filename);
+            goto err_out1;
+        }
+
+        assert(asprintf(&host_path, "%s/dump/%s", GET_GLOBAL_STATE()->workdir_path,
+                        sub_dir) != -1);
+        mkdir(host_path, 0777); // TODO: Check for errors other than EEXIST
+
+        base_name = basename(filename); // clobbers the filename buffer!
+        assert(asprintf(&host_path, "%s/dump/%s/%s", GET_GLOBAL_STATE()->workdir_path,
+                        sub_dir, base_name) != -1);
+
+    } else {
+        base_name = basename(filename); // clobbers the filename buffer!
+        assert(asprintf(&host_path, "%s/dump/%s", GET_GLOBAL_STATE()->workdir_path,
+                        base_name) != -1);
+    }

     // check if base_name is mkstemp() pattern, otherwise write/append to exact name
     char *pattern = strstr(base_name, "XXXXXX");
EOF
popd >/dev/null
NO_CHECKOUT=1 ./build_nyx_support.sh
popd >/dev/null
find . -name .git -type d -exec rm -rf '{}' +
find . -name \*.o -delete
find . -executable -type f -execdir strip '{}' + -o -true || true
popd >/dev/null
popd >/dev/null
apt-mark manual "$(dpkg -S /usr/lib/x86_64-linux-gnu/libpython3.\*.so.1 | cut -d: -f1)"

mkdir -p /srv/repos/ipc-research
chown -R worker:worker /home/worker /srv/repos

pushd /srv/repos >/dev/null
for r in fuzzfetch FuzzManager prefpicker guided-fuzzing-daemon; do
  git-clone "https://github.com/MozillaSecurity/$r"
  chown -R worker:worker "$r"
  # install then uninstall so only dependencies remain
  retry su worker -c "pip3 install ./$r"
  su worker -c "pip3 uninstall -y $r"
done
su worker -c "pip3 install ./nyx_ipc_manager"
popd >/dev/null

retry su worker -c "pip3 install google-cloud-storage psutil"
rm -rf /opt/clang /opt/rustc
/srv/repos/setup/cleanup.sh
