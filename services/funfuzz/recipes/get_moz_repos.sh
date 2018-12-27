#!/bin/bash -ex

function retry {
  # shellcheck disable=SC2015
  for _ in {1..9}; do
    "$@" && return || sleep 30
  done
  "$@"
}

pushd "$HOME"

# HG_FLAGS="retry $HOME/.local/bin/hg "
# Clone repositories using get_hg_repo.sh
mkdir -p trees/
pushd "$HOME/trees/"
# Note: hg clone works but we may want to switch to other script prior to deployment
# $HG_FLAGS clone https://hg.mozilla.org/mozilla-central mozilla-central
# curl -Ls https://git.io/fxxh4 | bash -s -- / mozilla-central trees/
# curl -Ls https://git.io/fxxh4 | bash -s -- /releases/ mozilla-beta trees/
popd

popd
