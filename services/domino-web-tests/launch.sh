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
  TASKCLUSTER_ROOT_URL="${TASKCLUSTER_PROXY_URL-$TASKCLUSTER_ROOT_URL}" retry taskcluster api secrets get "$1"
}

get-secret project/fuzzing/deploy-domino-web-tests | jshon -e secret -e key -u >.ssh/id_ecdsa.domino_web_tests
ln -s id_ecdsa.domino_web_tests .ssh/id_ecdsa
get-secret project/fuzzing/deploy-domino | jshon -e secret -e key -u >.ssh/id_rsa.domino
get-secret project/fuzzing/deploy-gridl | jshon -e secret -e key -u >.ssh/id_rsa.gridl
get-secret project/fuzzing/deploy-octo-private | jshon -e secret -e key -u >.ssh/id_rsa.octo
set -x
chmod 0400 .ssh/id_*

export PUPPETEER_PRODUCT=firefox
export EMAIL=nobody@community-tc.services.mozilla.com
export {GIT_AUTHOR_NAME,GIT_COMMITTER_NAME}="Taskcluster Automation"

git -c init.defaultBranch=clone init domino-web-tests
cd domino-web-tests
git remote add origin "${GIT_REPO-git@domino-web-tests:MozillaSecurity/domino-web-tests}"
retry git fetch -q --depth=10 origin "${GIT_BRANCH-master}"
git -c advice.detachedHead=false checkout "${GIT_REVISION-origin/master}"
retry npm i --no-progress

case "$ACTION" in
  trigger)
    retry npm i domino gridl
    git commit -a -m "Update domino and gridl revisions"
    retry git push origin HEAD:master
    ;;
  test)
    npm test
    if [ -f "test.results.html" ]; then
      mkdir results
      cp test.results.html results/
    fi
    ;;
  *)
    echo "unknown action: $ACTION" >&2
    exit 1
    ;;
esac
