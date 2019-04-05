#!/bin/bash -ex
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

cd "$HOME"

# Get fuzzmanager configuration from credstash
credstash get fuzzmanagerconf > .fuzzmanagerconf

# Update fuzzmanager config for this instance
mkdir -p signatures
cat >> .fuzzmanagerconf << EOF
sigdir = $HOME/signatures
EOF

# Add to base image?
curl https://sh.rustup.rs -sSf | sh -s -- -y
export PATH=$HOME/.cargo/bin:$PATH
export RUST_BACKTRACE=1
rustup install nightly
cargo install --force --git https://github.com/rust-fuzz/cargo-fuzz/

# ASan/LibFuzzer
export ASAN_OPTIONS=\
print_scariness=true:\
strip_path_prefix=/home/worker/u2f-hid-rs/:\
dedup_token_length=1:\
print_cmdline=true:\
detect_stack_use_after_scope=true:\
detect_invalid_pointer_pairs=1:\
strict_init_order=true:\
check_initialization_order=true:\
allocator_may_return_null=true:\
${ASAN}
export LIBFUZZER="u2f-hid-rs"
export LIBFUZZER_ARGS=("-print_pcs=1" "${TOKENS}" "${LIBFUZZER_ARGS}")

# Clone target
git clone --depth=1 https://github.com/jcjones/u2f-hid-rs
cd u2f-hid-rs

# Build target
cargo build

# Add FuzzManager target configuration
cat > /home/worker/.cargo/bin/rustup.fuzzmanagerconf << EOF
[Main]
platform = x86-64
product = ${LIBFUZZER}
product_version = $(git rev-parse --short HEAD)
os = $(uname -s)

[Metadata]
pathprefix = /home/worker/u2f-hid-rs/
buildflags =
EOF

# Need to figure out how to call the `u2f_read_write` executable differently so
# that we do not need to add a target's fuzzmanagerconf to `rustup`.
export COMMAND="/home/worker/.cargo/bin/rustup run nightly cargo fuzz run u2f_read_write"

../fuzzmanager/misc/libfuzzer/libfuzzer.py \
        --sigdir ../signatures \
        --tool "LibFuzzer-${LIBFUZZER}" \
        --env "${ASAN_OPTIONS//:/ }" \
        --cmd "${COMMAND}" -- "${LIBFUZZER_ARGS[@]}"
