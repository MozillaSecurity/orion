#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# %<---[Setup]----------------------------------------------------------------

WORKDIR=${WORKDIR:-$HOME}
cd "$WORKDIR" || exit

# shellcheck source=base/linux/fuzzos/recipes/common.sh
source ~/.local/bin/common.sh

# In some environments, we require credentials for talking to credstash
setup-aws-credentials "$SHIP"

if [[ -n "$OSSFUZZ_PROJECT" ]]
then
  if  [[ ! -d "$HOME/oss-fuzz" ]]
  then
    retry git clone --depth 1 https://github.com/google/oss-fuzz
  fi
  if [[ ! -f "$HOME/.boto" ]]
  then
    retry credstash get ossfuzz.gutils >> ~/.boto
  fi
fi

# Get FuzzManager configuration from credstash.
# We require FuzzManager credentials in order to submit our results.
if [[ ! -f "$HOME/.fuzzmanagerconf" ]]
then
  retry credstash get fuzzmanagerconf > .fuzzmanagerconf
fi

# Update FuzzManager config for this instance.
mkdir -p signatures
cat >> .fuzzmanagerconf << EOF
sigdir = $HOME/signatures
EOF

if [ -z "$VIRGO" ]
then
  # Update Fuzzmanager config with suitable hostname based on the execution environment.
  setup-fuzzmanager-hostname "$SHIP"
fi

# %<---[Target]---------------------------------------------------------------

# Our default target is Firefox, but we support targetting the JS engine instead.
# In either case, we check if the target is already mounted into the container.
TARGET_BIN="firefox/firefox"
JS=${JS:-0}
if [ "$JS" = 1 ]
then
  if [[ ! -d "$HOME/js" ]]
  then
    retry fuzzfetch -o "$HOME" -n js -a --fuzzing --target js
  fi
  TARGET_BIN="js/fuzz-tests"
elif [[ ! -d "$HOME/firefox" ]]
then
  retry fuzzfetch -o "$HOME" -n firefox -a --fuzzing --tests gtest
fi

# %<---[Constants]------------------------------------------------------------

FUZZDATA_URL="https://github.com/mozillasecurity/fuzzdata.git/trunk"
AFL_LIBFUZZER_DAEMON="./fuzzmanager/misc/afl-libfuzzer/afl-libfuzzer-daemon.py"

# IPC
if [ -n "$MOZ_IPC_MESSAGE_FUZZ_BLACKLIST" ]
then
  mkdir -p settings/ipc
  retry svn export --force "$FUZZDATA_URL/$MOZ_IPC_MESSAGE_FUZZ_BLACKLIST" "$MOZ_IPC_MESSAGE_FUZZ_BLACKLIST"
  export MOZ_IPC_MESSAGE_FUZZ_BLACKLIST="$HOME/$MOZ_IPC_MESSAGE_FUZZ_BLACKLIST"
fi

S3_PROJECT_ARGS=""
S3_QUEUE_UPLOAD_ARGS=""

# %<---[Corpora]--------------------------------------------------------------

if [ -n "$S3_PROJECT" ]
then
  # Use S3 for corpus management and synchronization. Each instance will download the corpus
  # from S3 (either by downloading a bundle or by downloading a fraction of files).
  # Whenever new coverage is found, that file is uploaded to an instance-unique queue on S3
  # so other instances can download it for sharing progress. When using this, it is important
  # to have a job on the build server that periodically recombines all open S3 queues
  # into a new corpus.

  # Generic parameters for S3
  S3_PROJECT_ARGS="--s3-bucket mozilla-aflfuzz --project $S3_PROJECT"

  # This option ensures that we synchronize local finds from/to S3 queues.
  # When generating coverage, it does not make sense to use this.
  if [ -z "$COVERAGE" ]
  then
    S3_QUEUE_UPLOAD_ARGS="--s3-queue-upload"
  fi

  # This can be used to download only a subset of corpus files for fuzzing
  CORPUS_DOWNLOAD_ARGS=""
  if [ -n "$S3_CORPUS_SUBSET_SIZE" ]
  then
    CORPUS_DOWNLOAD_ARGS="--s3-corpus-download-size $S3_CORPUS_SUBSET_SIZE"
  fi

  # Download the corpus from S3
  # shellcheck disable=SC2086
  $AFL_LIBFUZZER_DAEMON $CORPUS_DOWNLOAD_ARGS $S3_PROJECT_ARGS --s3-corpus-download corpora/
elif [ -n "$OSSFUZZ_PROJECT" ]
then
  # Use synced corpora from OSSFuzz.
  mkdir -p ./corpora
  ./oss-fuzz/infra/helper.py download_corpora --fuzz-target "$FUZZER" "$OSSFUZZ_PROJECT" || true
  CORPORA_PATH="./oss-fuzz/build/corpus/$OSSFUZZ_PROJECT/$FUZZER"
  if [ -d "$CORPORA_PATH" ]
  then
    set +x
    cp "$CORPORA_PATH"/* ./corpora/ || true
    set -x
  fi
elif [ -n "$CORPORA" ]
then
  # Use a static corpus instead
  retry svn export --force "$FUZZDATA_URL/$CORPORA" ./corpora/
else
  mkdir -p ./corpora
fi

CORPORA="./corpora/"

# %<---[Tokens]---------------------------------------------------------------

if [ -n "$TOKENS" ]
then
  retry svn export --force "$FUZZDATA_URL/$TOKENS" ./tokens.dict
  TOKENS="-dict=./tokens.dict"
fi

# %<---[Sanitizer]------------------------------------------------------------

export ASAN_SYMBOLIZER_PATH=/usr/bin/llvm-symbolizer

ASAN_OPTIONS=\
print_scariness=true:\
strip_path_prefix=/builds/worker/workspace/build/src/:\
dedup_token_length=1:\
print_cmdline=true:\
detect_stack_use_after_scope=true:\
detect_invalid_pointer_pairs=2:\
strict_init_order=true:\
check_initialization_order=true:\
allocator_may_return_null=true:\
start_deactivated=false:\
strict_string_checks=true:\
$ASAN

export ASAN_OPTIONS=${ASAN_OPTIONS//:/ }

UBSAN_OPTIONS=\
strip_path_prefix=/builds/worker/workspace/build/src/:\
print_stacktrace=1:\
print_summary=1:\
halt_on_error=1:\
$UBSAN

export UBSAN_OPTIONS=${UBSAN_OPTIONS//:/ }

# %<---[StatusFile]-----------------------------------------------------------

tee run-ec2report.sh << EOF
#!/bin/bash
./fuzzmanager/EC2Reporter/EC2Reporter.py --report-from-file ./stats --keep-reporting 60 --random-offset 30
EOF
chmod u+x run-ec2report.sh
screen -t ec2report -dmS ec2report ./run-ec2report.sh

# %<---[LibFuzzer]------------------------------------------------------------

export FUZZER="${FUZZER:-SdpParser}"
export LIBFUZZER=1
export MOZ_RUN_GTEST=1
# shellcheck disable=SC2206
LIBFUZZER_ARGS=($LIBFUZZER_ARGS $TOKEN $CORPORA)
if [ -z "$LIBFUZZER_INSTANCES" ]
then
  LIBFUZZER_INSTANCES=$(nproc)
fi

# Support auto reduction, format is "MIN;PERCENT".
LIBFUZZER_AUTOREDUCE_ARGS=""
if [ -n "$LIBFUZZER_AUTOREDUCE" ]
then
  IFS=';' read -r -a LIBFUZZER_AUTOREDUCE_PARAMS <<< "$LIBFUZZER_AUTOREDUCE"
  LIBFUZZER_AUTOREDUCE_ARGS="--libfuzzer-auto-reduce-min ${LIBFUZZER_AUTOREDUCE_PARAMS[0]} --libfuzzer-auto-reduce ${LIBFUZZER_AUTOREDUCE_PARAMS[1]}"
fi

# Run LibFuzzer
# shellcheck disable=SC2086
$AFL_LIBFUZZER_DAEMON $S3_PROJECT_ARGS $S3_QUEUE_UPLOAD_ARGS \
  --fuzzmanager \
  --libfuzzer $LIBFUZZER_AUTOREDUCE_ARGS \
  --libfuzzer-instances "$LIBFUZZER_INSTANCES" \
  --stats "./stats" \
  --sigdir "$HOME/signatures" \
  --tool "libFuzzer-$FUZZER" \
  --cmd "$HOME/$TARGET_BIN" "${LIBFUZZER_ARGS[@]}"
