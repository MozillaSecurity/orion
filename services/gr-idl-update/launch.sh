#!/bin/bash

set -e
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source /home/worker/.local/bin/common.sh

get-tc-secret deploy-gridl .ssh/gridl_deploy

GIT_TOKEN=$(get-tc-secret ci-git-token)
export GIT_TOKEN

npm set //registry.npmjs.org/:_authToken="$(get-tc-secret deploy-npm)"

set -x
chmod 0400 .ssh/*_deploy

export CI=1
export EMAIL=nobody@community-tc.services.mozilla.com
export {GIT_AUTHOR_NAME,GIT_COMMITTER_NAME}="Taskcluster Automation"

git init gridl
(
  cd gridl
  git remote add origin "${GIT_REPO-git@gridl:MozillaSecurity/gridl}"
  retry git fetch -q --depth=10 origin master
  git -c advice.detachedHead=false checkout origin/master
  retry npm i --no-progress
  npm run update-idls &&
  npm test &&
  if git status -s; then
    git add data/idls
    git commit -m "fix(grammar): update webidls"
    retry git push origin HEAD:master
  fi
)> /live.log 2>&1
