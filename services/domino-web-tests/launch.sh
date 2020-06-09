#!/bin/bash

set -e
set -x
set -o pipefail

export PUPPETEER_PRODUCT=firefox

function retry () {
  for _ in {1..9}; do
    "$@" && return
    sleep 30
  done
  "$@"
}

set +x
retry taskcluster api secrets get project/fuzzing/deploy-domino-web-tests | jshon -e secret -e key -u >.ssh/id_ecdsa.domino_web_tests
retry taskcluster api secrets get project/fuzzing/deploy-domino | jshon -e secret -e key -u >.ssh/id_rsa.domino
retry taskcluster api secrets get project/fuzzing/deploy-gridl | jshon -e secret -e key -u >.ssh/id_rsa.gridl
retry taskcluster api secrets get project/fuzzing/deploy-octo-private | jshon -e secret -e key -u >.ssh/id_rsa.octo
set -x
chmod 0400 .ssh/id_*

git init domino-web-tests
cd domino-web-tests
git remote add origin git@domino-web-tests:MozillaSecurity/domino-web-tests
retry git fetch -q --depth=5 origin master
git -c advice.detachedHead=false checkout origin/master
retry npm i --no-progress
retry npm update domino gridl
git commit -a -m "Update package-lock.json"
retry git push origin master
