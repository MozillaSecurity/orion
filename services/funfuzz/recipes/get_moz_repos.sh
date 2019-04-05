#!/bin/bash -ex
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

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
