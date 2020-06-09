#!/bin/bash

set -e
set -o pipefail

function retry () {
  for _ in {1..9}; do
    "$@" && return
    sleep 30
  done
  "$@"
}

function get-secret () {
  # taskcluster cli doesn't work .. why?
  # retry taskcluster api secrets get "$1"
  curl -sSL --retry 5 "http://taskcluster/secrets/v1/secret/$1"
}

get-secret project/fuzzing/deploy-domino-web-tests | jshon -e secret -e key -u >.ssh/id_ecdsa.domino_web_tests
ln -s id_ecdsa.domino_web_tests .ssh/id_ecdsa
get-secret project/fuzzing/deploy-domino | jshon -e secret -e key -u >.ssh/id_rsa.domino
get-secret project/fuzzing/deploy-gridl | jshon -e secret -e key -u >.ssh/id_rsa.gridl
get-secret project/fuzzing/deploy-octo-private | jshon -e secret -e key -u >.ssh/id_rsa.octo
set -x
chmod 0400 .ssh/id_*

export PUPPETEER_PRODUCT=firefox

git init domino-web-tests
cd domino-web-tests
git remote add origin "${GIT_REPO-git@domino-web-tests:MozillaSecurity/domino-web-tests}"
retry git fetch -q --depth=10 origin "${GIT_BRANCH-master}"
git -c advice.detachedHead=false checkout "${GIT_REVISION-origin/master}"
retry npm i --no-progress

case "$ACTION" in
  trigger)
    retry npm update domino gridl
    git commit -a -m "Update package-lock.json"
    retry git push origin master
    ;;
  test)
    npm test
    ;;
  *)
    echo "unknown action: $ACTION" >&2
    exit 1
    ;;
esac
