#!/bin/bash

set -e
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source ~/.local/bin/common.sh

get-tc-secret deploy-gr-css-reports .ssh/gr.css.reports_deploy

npm set //registry.npmjs.org/:_authToken="$(get-tc-secret deploy-npm)"

set -x
chmod 0400 .ssh/*_deploy

export CI=true
export EMAIL=nobody@community-tc.services.mozilla.com
export {GIT_AUTHOR_NAME,GIT_COMMITTER_NAME}="Taskcluster Automation"

# Install prefpicker
retry python3 -m pip install git+https://github.com/MozillaSecurity/prefpicker.git

# Fetch build
retry fuzzfetch -a --fuzzing -n nightly

git init gr.css.reports
(
  cd gr.css.reports
  git remote add origin "${GIT_REPO-git@gr-css-reports:MozillaSecurity/gr.css.reports}"
  retry git fetch -q --depth=10 origin main
  git -c advice.detachedHead=false checkout origin/main
  # Ignore the lockfile when installing both to ensure we have the latest
  # version of gr.css and gr.css.generator
  retry npm i
  python3 -m prefpicker browser-fuzzing.yml prefs.js
  npx @mozillasecurity/gr.css ~/nightly/firefox src/grammar.json -p prefs.js &&
  npm test &&
  if ! git diff --quiet src/grammar.json; then
    git commit -m "feat(grammar): update grammar" src/grammar.json
    retry git push origin HEAD:main
  fi
)> /live.log 2>&1
