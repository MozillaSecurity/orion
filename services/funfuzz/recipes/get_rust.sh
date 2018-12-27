#!/bin/bash -ex

function retry {
  # shellcheck disable=SC2015
  for _ in {1..9}; do
    "$@" && return || sleep 30
  done
  "$@"
}

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
