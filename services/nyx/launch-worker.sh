#!/usr/bin/env -S bash -l
set -e
set -x
set -o pipefail

id
ls -l /dev/kvm

# shellcheck source=recipes/linux/common.sh
source "/srv/repos/setup/common.sh"

for r in fuzzfetch FuzzManager prefpicker; do
  pushd "/srv/repos/$r" >/dev/null
  retry git fetch --depth=1 --no-tags origin
  git reset --hard FETCH_HEAD
  pip3 install -U .
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

gcs-dl-all () {
# gcs-dl-all bucket prefix dest
python3 - "$1" "$2" "$3" << "EOF"
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from google.cloud import storage

storage_client = storage.Client()
bucket = storage_client.bucket(sys.argv[1])

n_workers = len(os.sched_getaffinity(0))
prefix_path = PurePosixPath(sys.argv[2])
with ThreadPoolExecutor(max_workers=n_workers) as executor:
  for blob in bucket.list_blobs(prefix=sys.argv[2]):
    if blob.name.endswith("/"):
      continue
    blob_path = PurePosixPath(blob.name)
    dest = Path(sys.argv[3]) / blob_path.relative_to(prefix_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    executor.submit(blob.download_to_filename, dest)
EOF
}

# get Cloud Storage credentials
mkdir -p ~/.config/gcloud
get-tc-secret google-cloud-storage-guided-fuzzing ~/.config/gcloud/application_default_credentials.json raw

# pull corpus
time gcs-dl-all guided-fuzzing-data nyx-ipc-fuzzing/corpus ./corpus

# pull qemu image
if [[ ! -e ~/firefox.img ]]; then
  time gcs-cat guided-fuzzing-data ipc-fuzzing-vm/firefox.img.zst | zstd -do ~/firefox.img
fi
time gcs-cat guided-fuzzing-data ipc-fuzzing-vm/snapshot.tar.zst | zstdcat | tar -x

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
cd ipc-fuzzing/preload/harness
sed -i '23,26 {s/^/#/}' compile.sh
sed -i '38,41 {s/^/#/}' compile.sh
export CPPFLAGS="--sysroot /opt/sysroot-x86_64-linux-gnu -I/srv/repos/AFLplusplus/nyx_mode/QEMU-Nyx/libxdc"
./compile.sh
popd >/dev/null

# setup sharedir
pushd sharedir >/dev/null
fuzzfetch -n firefox --nyx --fuzzing --asan
find firefox/ -type d | sed 's/^/mkdir -p /' >> ff_files.sh
find firefox/ -type f | sed 's/.*/.\/hget_bulk \0 \0/' >> ff_files.sh
prefpicker browser-fuzzing.yml prefs.js
cp /srv/repos/ipc-research/ipc-fuzzing/preload/harness/sharedir/page.zip .
cp /srv/repos/ipc-research/ipc-fuzzing/preload/harness/sharedir/ld_preload_*.so .
cp -r /srv/repos/ipc-research/ipc-fuzzing/preload/harness/sharedir/htools .
cp htools/hget_no_pt .
popd >/dev/null

mkdir corpus.out

# run and watch for results
AFL_NYX_LOG=/logs/nyx.log \
/srv/repos/AFLplusplus/afl-fuzz -V 3600 -t 30000 -X -i ./corpus -o ./corpus.out -- ./sharedir
