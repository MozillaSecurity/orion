#!/usr/bin/env -S bash -l
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# KVM debugging info
id
ls -l /dev/kvm

# shellcheck source=recipes/linux/common.sh
source "/srv/repos/setup/common.sh"

for r in fuzzfetch FuzzManager prefpicker guided-fuzzing-daemon; do
  pushd "/srv/repos/$r" >/dev/null
  retry git fetch --depth=1 --no-tags origin HEAD
  git reset --hard FETCH_HEAD
  retry pip3 install -U .
  popd >/dev/null
done

update-status () {
  update-ec2-status "[$(date -Is)] $*"
}

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

get-deadline () {
  local tmp deadline started max_run_time run_end
  tmp="$(mktemp -d)"
  retry taskcluster api queue task "$TASK_ID" >"$tmp/task.json"
  retry taskcluster api queue status "$TASK_ID" >"$tmp/status.json"
  deadline="$(date --date "$(jshon -e status -e deadline -u <"$tmp/status.json")" +%s)"
  started="$(date --date "$(jshon -e status -e runs -e "$RUN_ID" -e started -u <"$tmp/status.json")" +%s)"
  max_run_time="$(jshon -e payload -e maxRunTime -u <"$tmp/task.json")"
  rm -rf "$tmp"
  run_end="$((started + max_run_time))"
  if [[ $run_end -lt $deadline ]]; then
    echo "$run_end"
  else
    echo "$deadline"
  fi
}

get-target-time () {
  if [[ -n "$TASK_ID" ]] || [[ -n "$RUN_ID" ]]; then
    echo $(($(get-deadline) - $(date +%s) - 5 * 60))
  else
    echo $((10 * 365 * 24 * 3600))
  fi
}

# get Cloud Storage credentials
mkdir -p ~/.config/gcloud
get-tc-secret google-cloud-storage-guided-fuzzing ~/.config/gcloud/application_default_credentials.json raw

# get AWS S3 credentials
setup-aws-credentials

# Get FuzzManager configuration
# We require FuzzManager credentials in order to submit our results.
if [[ ! -e ~/.fuzzmanagerconf ]]; then
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
  update-status "downloading firefox.img"
  time gcs-cat guided-fuzzing-data ipc-fuzzing-vm/firefox.img.zst | zstd -do ~/firefox.img
fi

# clone ipc-fuzzing & build harness/tools
# get deployment key from TC
if [[ ! -e /srv/repos/ipc-research/ipc-fuzzing ]]; then
update-status "installing ipc-fuzzing repo"
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
sed -i 's/ -fsanitize=address//' compile.sh
sed -i 's/ -O0/ -O2/' compile.sh
export CPPFLAGS="--sysroot /opt/sysroot-x86_64-linux-gnu -I/srv/repos/AFLplusplus/nyx_mode/QEMU-Nyx/libxdc"
./compile.sh
popd >/dev/null
fi

# create snapshot
if [[ ! -d ~/snapshot ]]; then
  update-status "creating snapshot"
  ./snapshot.sh
fi

# setup sharedir

ASAN_OPTIONS=\
abort_on_error=true:\
allocator_may_return_null=true:\
detect_leaks=0:\
hard_rss_limit_mb=4096:\
log_path=/tmp/data.log:\
max_allocation_size_mb=3073:\
strip_path_prefix=/builds/worker/workspace/build/src/:\
symbolize=0:\
$ASAN_OPTIONS
ASAN_OPTIONS=${ASAN_OPTIONS//:/ }

UBSAN_OPTIONS=\
strip_path_prefix=/builds/worker/workspace/build/src/:\
symbolize=0:\
$UBSAN_OPTIONS
UBSAN_OPTIONS=${UBSAN_OPTIONS//:/ }

NYX_PAGE="${NYX_PAGE-page.zip}"
NYX_PAGE_HTMLNAME="${NYX_PAGE_HTMLNAME-caniuse.html}"

pushd sharedir >/dev/null
if [[ ! -d firefox ]]; then
  update-status "downloading firefox"
  fuzzfetch -n firefox --nyx --fuzzing --asan
fi
{
  find firefox/ -type d | sed 's/^/mkdir -p /'
  find firefox/ -type f | sed 's/.*/.\/hget_bulk \0 \0/'
  find firefox/ -type f -executable | sed 's/.*/chmod +x \0/'
} > ff_files.sh
sed -i "s,\${ASAN_OPTIONS},$ASAN_OPTIONS," stage2.sh
sed -i "s,\${UBSAN_OPTIONS},$UBSAN_OPTIONS," stage2.sh
prefpicker browser-fuzzing.yml prefs.js
cp "/srv/repos/ipc-research/ipc-fuzzing/preload/harness/sharedir/$NYX_PAGE" .
cp /srv/repos/ipc-research/ipc-fuzzing/preload/harness/sharedir/ld_preload_*.so .
cp -r /srv/repos/ipc-research/ipc-fuzzing/preload/harness/sharedir/htools .
cp htools/hget_no_pt .
popd >/dev/null

mkdir -p corpus.out

update-status "preparing to launch guided-fuzzing-daemon"

if [[ -n "$TASK_ID" ]] || [[ -n "$RUN_ID" ]]; then
  python3 -m TaskStatusReporter --report-from-file ./stats --keep-reporting 60 --random-offset 30 &

  onexit () {
    # ensure final stats are complete
    python3 -m TaskStatusReporter --report-from-file ./stats
  }
  trap onexit EXIT
fi

if [[ -z "$NYX_INSTANCES" ]]; then
  NYX_INSTANCES="$(python3 -c "import psutil; print(psutil.cpu_count(logical=False))")"
fi

DAEMON_ARGS=(
  --afl-binary-dir /srv/repos/AFLplusplus
  --afl-timeout "${AFL_TIMEOUT-30000}"
  --nyx
  --sharedir ./sharedir
  --stats ./stats
)

S3_PROJECT="Nyx-$NYX_FUZZER"
S3_PROJECT_ARGS=(--s3-bucket mozilla-aflfuzz --project "$S3_PROJECT")

if [[ -n "$S3_CORPUS_REFRESH" ]]; then
  update-status "starting corpus refresh"
  if [[ "$NYX_FUZZER" = "IPC_SingleMessage" ]]; then
    guided-fuzzing-daemon --s3-list-projects "${S3_PROJECT_ARGS[@]}" | while read -r project; do
      time guided-fuzzing-daemon \
        --s3-bucket mozilla-aflfuzz --project "$project" \
        --build ./sharedir/firefox \
        --s3-corpus-refresh ./corpus \
        "${DAEMON_ARGS[@]}"
    done
  else
    time guided-fuzzing-daemon "${S3_PROJECT_ARGS[@]}" \
      --build ./sharedir/firefox \
      --s3-corpus-refresh ./corpus \
      "${DAEMON_ARGS[@]}"
  fi
else
  if [[ "$NYX_FUZZER" = "IPC_SingleMessage" ]]; then
    mkdir -p corpus.add
    xvfb-run nyx-ipc-manager --single --sharedir ./sharedir --file "$NYX_PAGE_HTMLNAME" --file-zip "$NYX_PAGE"
    DAEMON_ARGS+=(
      --nyx-add-corpus ./corpus.out/workdir/dump/seeds
    )
    source ./sharedir/config.sh
    S3_PROJECT_ARGS=(--s3-bucket mozilla-aflfuzz --project "$S3_PROJECT-${MOZ_FUZZ_IPC_TRIGGER//:/_}")
  elif [[ "$NYX_FUZZER" = "IPC_Generic" ]]; then
    nyx-ipc-manager --generic --sharedir ./sharedir --file "$NYX_PAGE_HTMLNAME" --file-zip "$NYX_PAGE"
  else
    echo "unknown $NYX_FUZZER" 1>&2
    exit 2
  fi

  if [[ -n "$TASK_ID" ]] || [[ -n "$RUN_ID" ]]; then
    DAEMON_ARGS+=(--afl-hide-logs)
  fi

  # Sometimes, don't download the existing corpus.
  # This can increase coverage in large targets and prevents bad corpora.
  # Results will be merged with the existing corpus on next refresh.
  if [[ $(python3 -c "import random;print(random.randint(1,100))") -le 98 ]]; then
    # Download the corpus from S3
    update-status "downloading corpus"
    time guided-fuzzing-daemon "${S3_PROJECT_ARGS[@]}" --s3-corpus-download ./corpus
  fi
  # Ensure corpus is not empty
  if [[ $(find ./corpus -type f | wc -l) -eq 0 ]]; then
    echo "Hello world" > ./corpus/input0
  fi

  # run and watch for results
  update-status "launching guided-fuzzing-daemon"
  time guided-fuzzing-daemon "${S3_PROJECT_ARGS[@]}" \
    --afl-log-pattern /logs/afl%d.log \
    --fuzzmanager \
    --max-runtime "$(get-target-time)" \
    --nyx-async-corpus \
    --nyx-instances "$NYX_INSTANCES" \
    --nyx-log-pattern /logs/nyx%d.log \
    --env-percent 75 AFL_CUSTOM_MUTATOR_LIBRARY=/srv/repos/AFLplusplus/custom_mutators/honggfuzz/honggfuzz-2b-chunked-mutator.so \
    --s3-queue-upload \
    --tool "$S3_PROJECT" \
    "${DAEMON_ARGS[@]}" \
    -i ./corpus \
    -o ./corpus.out
  for st in ./corpus.out/*/fuzzer_stats; do
    idx="$(basename "$(dirname "$st")")"
    cp "$st" "/logs/fuzzer_stats$idx.txt"
  done
fi
