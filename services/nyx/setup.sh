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
  libblocksruntime0
  libglib2.0-0
  libjpeg-turbo8
  libpixman-1-0
  libpng16-16
  libxml2
  netcat-openbsd
  openssh-client
  psmisc
  python3
  python3-dev
  python3-distutils
  python3-pip
  python3-setuptools
  python3-venv
  python3-wheel
  zstd
)

sys-update
apt-install-auto libblocksruntime-dev make
sys-embed "${pkgs[@]}"

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
git-clone-rev https://github.com/AFLplusplus/AFLplusplus d09950f4bb98431576b872436f0fbf773ab895db
pushd AFLplusplus >/dev/null
# Use proper AFL_NYX_AUX_SIZE for nyx_aux_string
retry-curl https://github.com/AFLplusplus/AFLplusplus/commit/bfb841d01383a4801a28b007c5f7039f2f28bef9.diff | git apply
# WIP 2-byte chunked variant of honggfuzz custom mutator
retry-curl https://github.com/AFLplusplus/AFLplusplus/commit/1b611bb30c14724f0f2eb9330772d30723ba122c.diff | git apply
git apply << "EOF"
diff --git a/custom_mutators/honggfuzz/Makefile b/custom_mutators/honggfuzz/Makefile
index 5c2fcddb..2dde8ba1 100644
--- a/custom_mutators/honggfuzz/Makefile
+++ b/custom_mutators/honggfuzz/Makefile
@@ -1,5 +1,5 @@

-CFLAGS = -O3 -funroll-loops -fPIC -Wl,-Bsymbolic
+CFLAGS = -O3 -funroll-loops -fPIC -fblocks -lBlocksRuntime -Wl,-Bsymbolic

 all: honggfuzz-mutator.so honggfuzz-2b-chunked-mutator.so

commit f5ceb29f2f61439de7adbe8494a2e305c586b904
Author: Jesse Schwartzentruber <truber@mozilla.com>
Date:   Fri Jul 14 13:20:02 2023 -0400

    Don't set rpath to mozfetch

diff --git a/src/afl-cc.c b/src/afl-cc.c
index 58d44e5d..4c23d153 100644
--- a/src/afl-cc.c
+++ b/src/afl-cc.c
@@ -1138,22 +1138,6 @@ static void edit_params(u32 argc, char **argv, char **envp) {

   if (!have_pic) { cc_params[cc_par_cnt++] = "-fPIC"; }

-  // in case LLVM is installed not via a package manager or "make install"
-  // e.g. compiled download or compiled from github then its ./lib directory
-  // might not be in the search path. Add it if so.
-  u8 *libdir = strdup(LLVM_LIBDIR);
-  if (plusplus_mode && strlen(libdir) && strncmp(libdir, "/usr", 4) &&
-      strncmp(libdir, "/lib", 4)) {
-
-    cc_params[cc_par_cnt++] = "-Wl,-rpath";
-    cc_params[cc_par_cnt++] = libdir;
-
-  } else {
-
-    free(libdir);
-
-  }
-
   if (getenv("AFL_HARDEN")) {

     cc_params[cc_par_cnt++] = "-fstack-protector-all";
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
make afl-fuzz afl-showmap
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
diff --git a/fuzz_runner/src/nyx/params.rs b/fuzz_runner/src/nyx/params.rs
index b3eab6a..c8fe559 100644
--- a/fuzz_runner/src/nyx/params.rs
+++ b/fuzz_runner/src/nyx/params.rs
@@ -152,7 +152,7 @@ impl QemuParams {
                         },
                         QemuNyxRole::Child => {
                             cmd.push("-fast_vm_reload".to_string());
-                            cmd.push(format!("path={}/snapshot/,load=on,pre_path={}", workdir, x.presnapshot));
+                            cmd.push(format!("path={}/snapshot/,load=on", workdir));
                         },
                     };
                 },
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
popd >/dev/null
./build_nyx_support.sh
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
popd >/dev/null

retry su worker -c "pip3 install google-cloud-storage psutil"
rm -rf /opt/clang /opt/rustc
/srv/repos/setup/cleanup.sh
