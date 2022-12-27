#!/bin/bash

set -e
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source ~/.local/bin/common.sh

get-tc-secret deploy-gr-css-reports .ssh/gr.css.reports_deploy

GRCSS_TOKEN=$(get-tc-secret ci-git-token)
export GRCSS_TOKEN

npm set //registry.npmjs.org/:_authToken="$(get-tc-secret deploy-npm)"

set -x
chmod 0400 .ssh/*_deploy

export CI=1
export EMAIL=nobody@community-tc.services.mozilla.com
export {GIT_AUTHOR_NAME,GIT_COMMITTER_NAME}="Taskcluster Automation"

# Install prefpicker
retry python3 -m pip install git+https://github.com/MozillaSecurity/prefpicker.git

# Fetch build
fuzzfetch -a --fuzzing -n nightly

git init gr.css.reports
(
  cd gr.css.reports
  git remote add origin "${GIT_REPO-git@gr-css-reports:MozillaSecurity/gr.css.reports}"
  retry git fetch -q --depth=10 origin v2
  git -c advice.detachedHead=false checkout origin/v2
  retry npm i --no-package-lock --no-progress --no-save
  retry npm i --no-package-lock --no-progress @mozillasecurity/gr.css@next
  python3 -m prefpicker browser-fuzzing.yml prefs.js
  npx gr.css ~/nightly/firefox src/grammar.json -p prefs.js &&
  npm test &&
  if ! git diff --quiet src/grammar.json; then
    git commit -m "chore(grammar): update grammar" src/grammar.json
    retry git push origin HEAD:v2
  fi
)> /live.log 2>&1
