#!/usr/bin/env -S bash -l
set -e
set -x
set -o pipefail

id
ls -l /dev/kvm

# shellcheck source=recipes/linux/common.sh
source "/srv/repos/setup/common.sh"

for r in fuzzfetch FuzzManager prefpicker guided-fuzzing-daemon; do
  pushd "/srv/repos/$r" >/dev/null
  retry git fetch --depth=1 --no-tags origin
  git reset --hard FETCH_HEAD
  retry pip3 install -U .
  popd >/dev/null
done

gcs-cat () {
# gcs-cat bucket path
python3 - "$1" "$2" << "EOF"
import os
import sys
from google.cloud import storage

client = storage.Client()
bucket = client.bucket(sys.argv[1])

blob = bucket.blob(sys.argv[2])
print(f"Downloading gs://{sys.argv[1]}/{sys.argv[2]}", file=sys.stderr)
with os.fdopen(sys.stdout.fileno(), "wb", closefd=False) as stdout:
    blob.download_to_file(stdout)
EOF
}

# get Cloud Storage credentials
mkdir -p ~/.config/gcloud
get-tc-secret google-cloud-storage-guided-fuzzing ~/.config/gcloud/application_default_credentials.json raw

# get AWS S3 credentials
setup-aws-credentials

S3_PROJECT="Nyx-$NYX_FUZZER"
S3_PROJECT_ARGS=(--s3-bucket mozilla-aflfuzz --project "$S3_PROJECT")

# Get FuzzManager configuration
# We require FuzzManager credentials in order to submit our results.
if [[ ! -e ~/.fuzzmanagerconf ]]
then
  get-tc-secret fuzzmanagerconf .fuzzmanagerconf
  # Update FuzzManager config for this instance.
  mkdir -p signatures
  cat >> .fuzzmanagerconf << EOF
sigdir = $HOME/signatures
EOF
  # Update Fuzzmanager config with suitable hostname based on the execution environment.
  setup-fuzzmanager-hostname
  chmod 0600 ~/.fuzzmanagerconf
fi

# pull qemu image
if [[ ! -e ~/firefox.img ]]; then
  time gcs-cat guided-fuzzing-data ipc-fuzzing-vm/firefox.img.zst | zstd -do ~/firefox.img
fi

# clone ipc-fuzzing & build harness/tools
# get deployment key from TC
get-tc-secret deploy-ipc-fuzzing ~/.ssh/id_ecdsa.ipc_fuzzing
cat << EOF >> ~/.ssh/config

Host ipc-fuzzing
HostName github.com
IdentitiesOnly yes
IdentityFile ~/.ssh/id_ecdsa.ipc_fuzzing
EOF
pushd /srv/repos/ipc-research >/dev/null
git-clone git@ipc-fuzzing:MozillaSecurity/ipc-fuzzing.git
cd ipc-fuzzing
sed -i '32 {s/^/#/}' userspace-tools/compile_64.sh
sed -i 's/^gcc /clang /' userspace-tools/compile_64.sh
sed -i 's/uint32_t bytes /uint64_t bytes /' userspace-tools/src/htools/hget.c
cd preload/harness
sed -i '23,26 {s/^/#/}' compile.sh
sed -i '38,41 {s/^/#/}' compile.sh
export CPPFLAGS="--sysroot /opt/sysroot-x86_64-linux-gnu -I/srv/repos/AFLplusplus/nyx_mode/QEMU-Nyx/libxdc"
./compile.sh
popd >/dev/null

# create snapshot
if [[ ! -d ~/snapshot ]]; then
  pushd /srv/repos/ipc-research/ipc-fuzzing/userspace-tools >/dev/null
  sed -i 's,^QEMU_PT_BIN.*,QEMU_PT_BIN=/srv/repos/AFLplusplus/nyx_mode/QEMU-Nyx/x86_64-softmmu/qemu-system-x86_64,' qemu_tool.sh
  sed -i 's/-vnc/-monitor tcp:127.0.0.1:55555,server,nowait -vnc/' qemu_tool.sh
  touch config.sh
  qemu-cmd () {
    set +x
    echo "$@" | nc -N 127.0.0.1 55555 >/dev/null
    set -x
  }
  gen-qemu-sendkeys () {
    set +x
    echo -n "$@" | while read -r -n1 letter; do
      case "$letter" in
        "")
          echo "spc"
          ;;
        "/")
          echo "shift-7"
          ;;
        '"')
          echo "shift-2"
          ;;
        "-")
          echo "slash"
          ;;
        ";")
          echo "shift-comma"
          ;;
        *)
          echo "$letter"
          ;;
      esac
    done | while read -r key; do
      echo "sendkey $key"
    done
    echo "sendkey ret"
    echo ""
    set -x
  }

  ./qemu_tool.sh create_snapshot ~/firefox.img 6144 ~/snapshot &
  sleep 120
  qemu-cmd "sendkey alt-f2"
  sleep 30
  qemu-cmd "$(gen-qemu-sendkeys gnome-terminal)"
  sleep 60
  qemu-cmd "$(gen-qemu-sendkeys "sudo screen -d -m bash -c \"sleep 5; /home/user/loader\"; exit")"
  sleep 90
  qemu-cmd "$(gen-qemu-sendkeys user)"
  wait
  popd >/dev/null
fi

ASAN_OPTIONS=\
abort_on_error=true:\
allocator_may_return_null=true:\
check_initialization_order=true:\
dedup_token_length=1:\
detect_invalid_pointer_pairs=2:\
detect_leaks=0:\
detect_stack_use_after_scope=true:\
hard_rss_limit_mb=4096:\
log_path=/tmp/data.log:\
max_allocation_size_mb=3073:\
print_cmdline=true:\
print_scariness=true:\
start_deactivated=false:\
strict_init_order=true:\
strict_string_checks=true:\
strip_path_prefix=/builds/worker/workspace/build/src/:\
symbolize=0:\
$ASAN_OPTIONS
ASAN_OPTIONS=${ASAN_OPTIONS//:/ }

UBSAN_OPTIONS=\
halt_on_error=1:\
print_stacktrace=1:\
print_summary=1:\
strip_path_prefix=/builds/worker/workspace/build/src/:\
symbolize=0:\
$UBSAN_OPTIONS
UBSAN_OPTIONS=${UBSAN_OPTIONS//:/ }

#setup sharedir
pushd sharedir >/dev/null
if [[ ! -d firefox ]]; then
  fuzzfetch -n firefox --nyx --fuzzing --asan
fi
{
  find firefox/ -type d | sed 's/^/mkdir -p /'
  find firefox/ -type f | sed 's/.*/.\/hget_bulk \0 \0/'
  find firefox/ -type f -executable | sed 's/.*/chmod +x \0/'
} >> ff_files.sh
sed -i "s/\${NYX_FUZZER}/$NYX_FUZZER/" stage2.sh
sed -i "s,\${ASAN_OPTIONS},$ASAN_OPTIONS," stage2.sh
sed -i "s,\${UBSAN_OPTIONS},$UBSAN_OPTIONS," stage2.sh
prefpicker browser-fuzzing.yml prefs.js
cp /srv/repos/ipc-research/ipc-fuzzing/preload/harness/sharedir/page.zip .
cp /srv/repos/ipc-research/ipc-fuzzing/preload/harness/sharedir/ld_preload_*.so .
cp -r /srv/repos/ipc-research/ipc-fuzzing/preload/harness/sharedir/htools .
cp htools/hget_no_pt .
popd >/dev/null

mkdir corpus.out

if [[ -z "$NYX_INSTANCES" ]]
then
  NYX_INSTANCES="$(nproc)"
fi

export AFL_NYX_LOG=/logs/nyx.log

if [[ -n "$S3_CORPUS_REFRESH" ]]
then
  time guided-fuzzing-daemon "${S3_PROJECT_ARGS[@]}" --nyx --s3-corpus-refresh ./corpus
else
  # Download the corpus from S3
  time guided-fuzzing-daemon "${S3_PROJECT_ARGS[@]}" --s3-corpus-download ./corpus
  # run and watch for results
  mkdir -p corpus.out
  time guided-fuzzing-daemon "${S3_PROJECT_ARGS[@]}" --afl-binary-dir /srv/repos/AFLplusplus --sharedir ./sharedir --fuzzmanager --s3-queue-upload --tool "$S3_PROJECT" --nyx --nyx-instances "$NYX_INSTANCES" --afl-timeout 30000 ./corpus ./corpus.out
fi
