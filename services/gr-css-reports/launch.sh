#!/bin/bash

set -e
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source ~/.local/bin/common.sh

get-tc-secret deploy-gr-css .ssh/gr.css_deploy
get-tc-secret deploy-gr-css-generator .ssh/gr.css.generator_deploy
get-tc-secret deploy-gr-css-reports .ssh/gr.css.reports_deploy
get-tc-secret deploy-octo-private .ssh/octo_private_deploy
GH_TOKEN=$(get-tc-secret git-token-gr-css)
export GH_TOKEN

set -x
chmod 0400 .ssh/*_deploy

export CI=1
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
  if ! git diff --quiet src/grammar.json; then
    git commit -m "chore(grammar): update grammar" src/grammar.json
    retry git push origin HEAD:main
  fi
)> /live.log 2>&1
