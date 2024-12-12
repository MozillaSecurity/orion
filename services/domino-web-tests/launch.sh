#!/bin/bash

set -e
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

get-tc-secret project/fuzzing/deploy-domino-web-tests >.ssh/id_ecdsa.domino_web_tests
ln -s id_ecdsa.domino_web_tests .ssh/id_ecdsa
get-tc-secret project/fuzzing/deploy-domino >.ssh/id_rsa.domino
get-tc-secret project/fuzzing/deploy-gridl >.ssh/id_rsa.gridl
get-tc-secret project/fuzzing/deploy-octo-private >.ssh/id_rsa.octo
set -x
chmod 0400 .ssh/id_*

export PUPPETEER_PRODUCT=firefox
export EMAIL=nobody@community-tc.services.mozilla.com
export {GIT_AUTHOR_NAME,GIT_COMMITTER_NAME}="Taskcluster Automation"

git init domino-web-tests
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
