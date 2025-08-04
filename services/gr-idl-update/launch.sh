#!/bin/bash

set -e
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source /home/worker/.local/bin/common.sh

get-tc-secret deploy-gridl .ssh/gridl_deploy

GITHUB_TOKEN=$(get-tc-secret ci-git-token)
export GITHUB_TOKEN

npm set //registry.npmjs.org/:_authToken="$(get-tc-secret deploy-npm)"

set -x
chmod 0400 .ssh/*_deploy

export CI=1

git init gridl
(
  cd gridl
  git remote add origin "${GIT_REPO-git@gridl:MozillaSecurity/gridl}"
  retry git fetch -q --depth=1 origin main
  git -c advice.detachedHead=false checkout origin/main
  git config user.name "Taskcluster Automation"
  git config user.email "fuzzing@mozilla.com"
  retry npm i --no-progress
  npm run update-idls &&
    npm test &&
    if git status -s; then
      git add data/idls
      git commit -m "feat(grammar): update webidls"
      retry git push origin HEAD:main
    fi
) >/live.log 2>&1
