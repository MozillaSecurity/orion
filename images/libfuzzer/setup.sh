#!/bin/bash -ex

if [[ $COVERAGE ]]
then
    echo "Launching coverage LibFuzzer run."
    ./coverage.sh
else
    echo "Launching LibFuzzer run."
    ./libfuzzer.sh
fi
