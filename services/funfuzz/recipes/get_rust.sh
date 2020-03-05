#!/bin/bash -ex
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# shellcheck source=base/linux/fuzzos/recipes/common.sh
source ~/.local/bin/common.sh

pushd "$HOME"

RUSTUP_FLAGS="retry $HOME/.cargo/bin/rustup "
RUSTC_FLAGS="retry $HOME/.cargo/bin/rustc "

# Install Rust using rustup
curl https://sh.rustup.rs -sSf | sh -s -- -y
$RUSTUP_FLAGS update stable
$RUSTUP_FLAGS target add i686-unknown-linux-gnu
$RUSTUP_FLAGS --version
$RUSTC_FLAGS --version

popd
