#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=recipes/linux/common.sh
source ~/.local/bin/common.sh

function onExit {
    echo "Script is terminating - executing trap commands."
    disable-ec2-pool "$EC2SPOTMANAGER_POOLID"
}

if [[ $COVERAGE ]]
then
    trap onExit EXIT
    echo "Launching coverage LibFuzzer run."
    ./coverage.sh
else
    echo "Launching LibFuzzer run."
    ./libfuzzer.sh
fi
