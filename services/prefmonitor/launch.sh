#!/bin/bash

set -e
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source /home/worker/.local/bin/common.sh

GITHUB_TOKEN=$(get-tc-secret prefmonitor-ci-token)
export GITHUB_TOKEN

set -x

export CI=1
export EMAIL=nobody@community-tc.services.mozilla.com
export {GIT_AUTHOR_NAME,GIT_COMMITTER_NAME}="PrefMonitor"

git config --global init.defaultBranch main
git init prefmonitor
(
  cd prefmonitor
  git remote add origin https://github.com/MozillaSecurity/prefpicker-monitor.git
  retry git fetch -q --depth=10 origin main
  git -c advice.detachedHead=false checkout origin/main
  poetry update
  poetry run prefmonitor
)> /live.log 2>&1
