#!/bin/bash -ex
cd $HOME

# Get fuzzmanager configuration from credstash
credstash get fuzzmanagerconf > .fuzzmanagerconf

# Update fuzzmanager config for this instance
mkdir -p signatures
cat >> .fuzzmanagerconf << EOF
sigdir = $HOME/signatures
EOF

# FuzzFetch
fuzzfetch -o $HOME -n firefox -a --fuzzing --tests gtest

# Firefox with ASan-/Coverage/LibFuzzer
cd firefox

# FuzzData
FUZZDATA_URL="https://github.com/mozillasecurity/fuzzdata.git/trunk"

# Corpora
if [[ -n "${CORPORA}" ]]
then
  svn export --force ${FUZZDATA_URL}/${CORPORA} ../corpora/
  CORPORA="../corpora/"
fi

# Tokens
if [[ -n "${TOKENS}" ]]
then
  svn export --force ${FUZZDATA_URL}/${TOKENS} ../tokens.dict
  TOKENS="-dict=../tokens.dict"
fi

# ASan/LibFuzzer
export ASAN_OPTIONS=\
print_scariness=true:\
strip_path_prefix=/home/worker/workspace/build/src/:\
dedup_token_length=1:\
print_cmdline=true:\
detect_stack_use_after_scope=true:\
detect_invalid_pointer_pairs=1:\
strict_init_order=true:\
check_initialization_order=true:\
allocator_may_return_null=true:\
${ASAN}
export LIBFUZZER=${LIBFUZZER:-SdpParser}
export LIBFUZZER_ARGS="-print_pcs=1 ${TOKENS} ${LIBFUZZER_ARGS}"
export MOZ_RUN_GTEST=1

xvfb-run -s '-screen 0 1024x768x24' \
    ../fuzzmanager/misc/libfuzzer/libfuzzer.py \
        --sigdir ../signatures \
        --tool LibFuzzer-${LIBFUZZER} \
        --env ${ASAN_OPTIONS//:/ } \
        --cmd ./firefox ${LIBFUZZER_ARGS} ${CORPORA}

# Minimize Crash
#   xvfb-run -s '-screen 0 1024x768x24' ./firefox -minimize_crash=1 -max_total_time=60 crash-<hash>

# ASan Options
#   start_deactivated=true
#   handle_ioctl=true
#   detect_deadlocks=true
#   intercept_tls_get_addr=true
#   leak_check_at_exit=true # LSAN not enabled in --enable-fuzzing
#   strict_string_checks=false # GLib textdomain() error
#   detect_stack_use_after_return=false # nsXPConnect::InitStatics() error

# LibFuzzer Options
# -jobs=4 # not supported yet by libfuzzer.py
