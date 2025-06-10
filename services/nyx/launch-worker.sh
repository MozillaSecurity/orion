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

COVERAGE="${COVERAGE-0}"

# shellcheck source=recipes/linux/common.sh
source "/srv/repos/setup/common.sh"

# generate commands for copying a directory recursively and maintaining
# executable permissions.
function make-copy-commands() {
  local dir="$1"
  if [[ -z $dir ]]; then
    echo "Usage: generate_commands <directory>"
    return 1
  fi

  if [[ ! -d $dir ]]; then
    echo "Error: Directory '$dir' does not exist."
    return 1
  fi

  find "$dir" -type d | sed 's|^|mkdir -p |'
  find "$dir" -type f | sed 's|.*|./hget_bulk & &|'
  find "$dir" -type f -executable | sed 's|.*|chmod +x &|'
}

function setup-ssh-key() {
  local host="$1"
  local key_path="$2"
  cat <<EOF >>~/.ssh/config
Host $host
HostName github.com
IdentitiesOnly yes
IdentityFile $key_path
EOF
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
  cat >>.fuzzmanagerconf <<EOF
sigdir = $HOME/signatures
EOF
  # Update Fuzzmanager config with suitable hostname based on the execution environment.
  setup-fuzzmanager-hostname
  chmod 0600 ~/.fuzzmanagerconf
fi

# pull qemu image
if [[ ! -e ~/firefox.img ]]; then
  update-status "downloading firefox.img"
  time nyx-gcs-cat guided-fuzzing-data ipc-fuzzing-vm/firefox.img.zst | zstd -do ~/firefox.img
fi

pushd /srv/repos/ipc-research
# clone ipc-fuzzing & build harness/tools
if [[ ! -e /srv/repos/ipc-research/ipc-fuzzing ]]; then
  update-status "installing ipc-fuzzing repo"
  get-tc-secret deploy-ipc-fuzzing ~/.ssh/id_ecdsa.ipc_fuzzing
  setup-ssh-key "ipc-fuzzing" "$HOME/.ssh/id_ecdsa.ipc_fuzzing"
  git-clone git@ipc-fuzzing:MozillaSecurity/ipc-fuzzing.git
fi
pushd ipc-fuzzing/userspace-tools
export CPPFLAGS="--sysroot /opt/sysroot-x86_64-linux-gnu -I/srv/repos/AFLplusplus/nyx_mode/QEMU-Nyx/libxdc"

# Record crashes for non-default handlers
for var in CATCH_MOZ_CRASH CATCH_MOZ_ASSERT CATCH_MOZ_RELEASE_ASSERT; do
  if [[ ${!var} -eq 1 ]]; then
    export CPPFLAGS="$CPPFLAGS -D$var"
  fi
done

make clean htools_no_pt
cd ../preload/harness
make clean bin64/ld_preload_fuzz_no_pt.so
popd >/dev/null # /srv/repos/ipc-research/
popd >/dev/null # /home/worker/

# create snapshot
if [[ ! -d ~/snapshot ]]; then
  update-status "creating snapshot"
  ./snapshot.sh
fi

# setup sharedir

export AFL_NYX_HANDLE_INVALID_WRITE=1
export AFL_SKIP_BIN_CHECK=1

NYX_PAGE="${NYX_PAGE-page.zip}"
NYX_PAGE_HTMLNAME="${NYX_PAGE_HTMLNAME-caniuse.html}"

pushd sharedir >/dev/null
if [[ ! -d firefox ]]; then
  update-status "downloading firefox"

  default_args=(
    --nyx
    --fuzzing
    --asan
  )
  if [[ $COVERAGE -eq 1 ]]; then
    default_args+=(--coverage)
    if [[ -z $REVISION ]]; then
      default_args+=(
        --build "$(retry-curl --compressed https://community-tc.services.mozilla.com/api/index/v1/task/project.fuzzing.coverage-revision.latest/artifacts/public/coverage-revision.txt)"
      )
    fi
  fi

  # shellcheck disable=SC2086
  retry fuzzfetch -n firefox ${FUZZFETCH_FLAGS-${default_args[@]}}
fi
make-copy-commands firefox/ >ff_files.sh
sed -i "s,\${ASAN_OPTIONS},$ASAN_OPTIONS," stage2.sh
sed -i "s,\${UBSAN_OPTIONS},$UBSAN_OPTIONS," stage2.sh
sed -i "s,\${COVERAGE},$COVERAGE," stage2.sh
prefpicker browser-fuzzing.yml prefs.js
cp "/srv/repos/ipc-research/ipc-fuzzing/preload/harness/sharedir/$NYX_PAGE" .
cp /srv/repos/ipc-research/ipc-fuzzing/preload/harness/bin64/ld_preload_*.so .
mkdir -p htools
cp /srv/repos/ipc-research/ipc-fuzzing/userspace-tools/bin64/h* htools
cp htools/hget_no_pt .

# Set up ephemeral session variables
rm -f session.sh && touch session.sh

ASAN_OPTIONS=abort_on_error=true:allocator_may_return_null=true:detect_leaks=0:hard_rss_limit_mb=8192:log_path=/tmp/data.log:max_allocation_size_mb=3073:strip_path_prefix=/builds/worker/workspace/build/src/:symbolize=0:$ASAN_OPTIONS

UBSAN_OPTIONS=strip_path_prefix=/builds/worker/workspace/build/src/:symbolize=0:$UBSAN_OPTIONS

{
  echo "export ASAN_OPTIONS=\"${ASAN_OPTIONS}\""
  echo "export UBSAN_OPTIONS=\"${UBSAN_OPTIONS}\""
} >>session.sh

if [[ $COVERAGE -eq 1 ]]; then
  echo "export MOZ_FUZZ_COVERAGE=1" >>session.sh
fi

if [[ -n $AFL_PC_FILTER_FILE_REGEX ]] && [[ $COVERAGE -ne 1 ]]; then
  python3 /srv/repos/AFLplusplus/utils/dynamic_covfilter/make_symbol_list.py ./firefox/libxul.so >libxul.symbols.txt
  grep -P "$AFL_PC_FILTER_FILE_REGEX" libxul.symbols.txt >target.symbols.txt
  echo "export __AFL_PC_FILTER=1" >>session.sh
fi

popd >/dev/null # /home/worker/

if [[ $NYX_FUZZER == Domino* ]]; then
  export STRATEGY="${NYX_FUZZER##*-}"
  if [[ -z $STRATEGY ]]; then
    echo "could not identify domino strategy from: $NYX_FUZZER" 1>&2
    exit 2
  fi

  if [[ ! -d domino ]]; then
    update-status "installing domino"
    get-tc-secret deploy-domino ~/.ssh/id_ecdsa.domino
    setup-ssh-key "domino" "$HOME/.ssh/id_ecdsa.domino"
    git-clone git@domino:MozillaSecurity/domino.git
    pushd domino/ >/dev/null
    set +x
    npm set //registry.npmjs.org/:_authToken="$(get-tc-secret deploy-npm)" &&
      set -x
    npm install
    popd >/dev/null # /home/worker/
  fi
  node domino/lib/bin/server.js --is-nyx --strategy "$STRATEGY" &
fi

mkdir -p corpus.out

rev="$(grep SourceStamp= sharedir/firefox/platform.ini | cut -d= -f2)"

# download coverage opt build to calculate line-clusters
if [[ $COVERAGE -eq 1 ]] && [[ ! -e lineclusters.json ]]; then
  mkdir -p corpus.out/workdir/dump
  retry fuzzfetch -n cov-opt --fuzzing --coverage --build "$rev"
  prefix="$(grep pathprefix cov-opt/firefox.fuzzmanagerconf | cut -d\  -f3-)"
  python3 /srv/repos/ipc-research/ipc-fuzzing/code-coverage/postprocess-gcno.py lineclusters.json cov-opt "$prefix"
  rm -rf cov-opt
fi

update-status "preparing to launch guided-fuzzing-daemon"

if [[ -n $TASK_ID ]] || [[ -n $RUN_ID ]]; then
  task-status-reporter --report-from-file ./stats --keep-reporting 60 --random-offset 30 &

  onexit() {
    # ensure final stats are complete
    if [[ -e ./stats ]]; then
      task-status-reporter --report-from-file ./stats
    fi
  }
  trap onexit EXIT
fi

if [[ -z $NYX_INSTANCES ]]; then
  NYX_INSTANCES="$(nyx-ncpu)"
fi

DAEMON_ARGS=(
  --afl-binary-dir /srv/repos/AFLplusplus
  --afl-log-pattern /logs/afl%d.log
  --nyx
  --nyx-log-pattern /logs/nyx%d.log
  --sharedir ./sharedir
  --stats ./stats
  --timeout "${AFL_TIMEOUT-30000}"
)

S3_PROJECT="${S3_PROJECT-Nyx-$NYX_FUZZER}"
S3_PROJECT_ARGS=(--bucket mozilla-aflfuzz --project "$S3_PROJECT")

if [[ -n $S3_CORPUS_REFRESH ]]; then
  update-status "starting corpus refresh"
  export AFL_PRINT_FILENAMES=1
  if [[ $NYX_FUZZER == "IPC_SingleMessage" ]]; then
    guided-fuzzing-daemon --list-projects "${S3_PROJECT_ARGS[@]}" | while read -r project; do
      time guided-fuzzing-daemon \
        --bucket mozilla-aflfuzz \
        --project "$project" \
        --corpus-refresh ./corpus \
        "${DAEMON_ARGS[@]}"
    done
  else
    time guided-fuzzing-daemon "${S3_PROJECT_ARGS[@]}" \
      --corpus-refresh ./corpus \
      "${DAEMON_ARGS[@]}"
  fi
else
  if [[ $NYX_FUZZER == "IPC_SingleMessage" ]]; then
    mkdir -p corpus.add
    xvfb-run nyx-ipc-manager --single --sharedir ./sharedir --file "$NYX_PAGE_HTMLNAME" --file-zip "$NYX_PAGE"
    DAEMON_ARGS+=(
      --afl-add-corpus ./corpus.out/workdir/dump/seeds
      --env-percent 75 AFL_CUSTOM_MUTATOR_LIBRARY=/srv/repos/AFLplusplus/custom_mutators/honggfuzz/honggfuzz-2b-chunked-mutator.so
    )
    source ./sharedir/config.sh
    S3_PROJECT_ARGS=(--bucket mozilla-aflfuzz --project "$S3_PROJECT-${MOZ_FUZZ_IPC_TRIGGER//:/_}")
  elif [[ $NYX_FUZZER == "IPC_Generic" ]]; then
    DAEMON_ARGS+=(
      --env-percent 75 AFL_CUSTOM_MUTATOR_LIBRARY=/srv/repos/AFLplusplus/custom_mutators/honggfuzz/honggfuzz-2b-chunked-mutator.so
    )
    nyx-ipc-manager --generic --sharedir ./sharedir --file "$NYX_PAGE_HTMLNAME" --file-zip "$NYX_PAGE"
  elif [[ $NYX_FUZZER == Domino* ]]; then
    export AFL_CUSTOM_MUTATOR_LIBRARY=/srv/repos/AFLplusplus/custom_mutators/web_service_mutator/web_service_mutator.so
    export AFL_CUSTOM_MUTATOR_ONLY="1"
    export AFL_DISABLE_TRIM="1"
    echo "export NYX_FUZZER=\"$NYX_FUZZER\"" >>./sharedir/config.sh
  else
    echo "unknown fuzzer! ($NYX_FUZZER)" 1>&2
    exit 2
  fi

  if [[ -n $TASK_ID ]] || [[ -n $RUN_ID ]]; then
    DAEMON_ARGS+=(--afl-hide-logs)
  fi

  # Sometimes, don't download the existing corpus.
  # This can increase coverage in large targets and prevents bad corpora.
  # Results will be merged with the existing corpus on next refresh.
  if [[ $COVERAGE -eq 1 ]] || [[ $(python3 -c "import random;print(random.randint(1,100))") -le 98 ]]; then
    # Download the corpus from S3
    update-status "downloading corpus"
    time guided-fuzzing-daemon "${S3_PROJECT_ARGS[@]}" --corpus-download ./corpus
  else
    mkdir -p corpus
  fi
  # Ensure corpus is not empty
  if [[ $(find ./corpus -type f | wc -l) -eq 0 ]]; then
    echo "Hello world" >./corpus/input0
  fi

  if [[ $COVERAGE -eq 1 ]]; then
    export AFL_FAST_CAL=1
  fi

  # run and watch for results
  update-status "launching guided-fuzzing-daemon"
  time guided-fuzzing-daemon "${S3_PROJECT_ARGS[@]}" \
    --fuzzmanager \
    --max-runtime "$(get-target-time)" \
    --afl-async-corpus \
    --instances "$NYX_INSTANCES" \
    --queue-upload \
    --tool "$S3_PROJECT" \
    "${DAEMON_ARGS[@]}" \
    -i ./corpus \
    -o ./corpus.out
  for st in ./corpus.out/*/fuzzer_stats; do
    idx="$(basename "$(dirname "$st")")"
    cp "$st" "/logs/fuzzer_stats$idx.txt"
  done
fi

if [[ $COVERAGE -eq 1 ]]; then
  # Process coverage data
  prefix="$(grep pathprefix sharedir/firefox/firefox.fuzzmanagerconf | cut -d\  -f3-)"
  if [[ -e ./corpus.out/0/covmap.dump ]]; then
    cp ./corpus.out/0/covmap.dump ./corpus.out/workdir/dump
  fi
  cp ./corpus.out/workdir/dump/pcmap.dump /covdata/ || true
  cp ./corpus.out/workdir/dump/covmap.dump /covdata/ || true
  cp ./corpus.out/workdir/dump/modinfo.txt /covdata/ || true
  python3 /srv/repos/ipc-research/ipc-fuzzing/code-coverage/nyx-code-coverage.py \
    ./corpus.out/workdir/dump/ \
    ./lineclusters.json \
    "$prefix" \
    "$rev" \
    ./sharedir \
    ./coverage.json

  # Submit coverage data.
  cov-reporter \
    --repository mozilla-central \
    --description "$S3_PROJECT" \
    --tool "$S3_PROJECT" \
    --submit ./coverage.json
fi
