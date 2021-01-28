#!/bin/bash

set -e
set -o pipefail

function get-secret () {
  TASKCLUSTER_ROOT_URL="${TASKCLUSTER_PROXY_URL-$TASKCLUSTER_ROOT_URL}" retry taskcluster api secrets get "$1"
}

source ~/.local/bin/common.sh

get-secret project/fuzzing/deploy-gr-css | jshon -e secret -e key -u >.ssh/gr.css_deploy
get-secret project/fuzzing/deploy-gr-css-generator | jshon -e secret -e key -u >.ssh/gr.css.generator_deploy
get-secret project/fuzzing/deploy-gr-css-reports | jshon -e secret -e key -u >.ssh/gr.css.reports_deploy
get-secret project/fuzzing/deploy-octo-private | jshon -e secret -e key -u >.ssh/octo_private_deploy
export GH_TOKEN=$(get-secret project/fuzzing/git-token-gr-css | jshon -e secret -e key -u)

set -x
chmod 0400 .ssh/*_deploy

export EMAIL=nobody@community-tc.services.mozilla.com
export {GIT_AUTHOR_NAME,GIT_COMMITTER_NAME}="Taskcluster Automation"

# Fetch build
fuzzfetch -a --fuzzing -n nightly

git init gr.css.reports
(
  cd gr.css.reports
  git remote add origin "${GIT_REPO-git@gr-css-reports:MozillaSecurity/gr.css.reports}"
  retry git fetch -q --depth=10 origin main
  git -c advice.detachedHead=false checkout origin/main
  retry npm i --no-progress
  retry npm i --no-save --no-progress --production git+ssh://git@gr-css/mozillasecurity/gr.css.git
  node node_modules/gr.css/dist/gr.css.js ~/nightly/firefox src/grammar.json --token "$GH_TOKEN" &&
  npm test &&
  git commit -m "chore(grammar): update grammar" src/grammar.json
  # retry git push origin HEAD:main
)> /live.log 2>&1
