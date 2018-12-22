#!/usr/bin/env bash
set -e
set -x

# shellcheck disable=SC1090
source ~/.common.sh

function onExit {
    echo "Script is terminating - executing trap commands."
    disable-ec2-pool "$EC2SPOTMANAGER_POOLID"
}
trap onExit EXIT

if [[ $COVERAGE ]]
then
    echo "Launching coverage LibFuzzer run."
    ./coverage.sh
else
    echo "Launching LibFuzzer run."
    ./libfuzzer.sh
fi
