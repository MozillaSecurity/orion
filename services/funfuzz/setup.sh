#!/bin/bash -ex
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

pushd "/tmp"

./recipes/ssh_fuzzmanager_setup.sh
./recipes/get_rust.sh
./recipes/get_non_moz_repos.sh
./recipes/get_pip_packages.sh
./recipes/set_mercurial_config.sh
./recipes/set_vim_config.sh
./recipes/get_moz_repos.sh
./recipes/set_bashrc_options.sh
# Note: set core file options on host prior to deployment

popd
