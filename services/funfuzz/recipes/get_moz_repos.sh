#!/bin/bash -ex

# shellcheck disable=SC1090
source ~/.common.sh

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
