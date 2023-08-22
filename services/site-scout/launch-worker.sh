#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source ~/.local/bin/common.sh

eval "$(ssh-agent -s)"
mkdir -p .ssh

pushd /src/fuzzmanager >/dev/null
  retry git fetch -q --depth 1 --no-tags origin master
  git reset --hard origin/master
popd >/dev/null

# Get fuzzmanager configuration from TC
get-tc-secret fuzzmanagerconf-site-scout .fuzzmanagerconf

# Update fuzzmanager config for this instance
mkdir -p signatures
cat >> .fuzzmanagerconf << EOF
sigdir = $HOME/signatures
EOF
setup-fuzzmanager-hostname
chmod 0600 .fuzzmanagerconf

# Install site-scout
update-ec2-status "Setup: installing site-scout"
retry python3 -m pip install fuzzfetch git+https://github.com/MozillaSecurity/site-scout

# Clone site-scout private
# only clone if it wasn't already mounted via docker run -v
if [[ ! -d /src/site-scout-private ]]; then
  update-ec2-status "Setup: cloning site-scout-private"

  # Get deployment key from TC
  get-tc-secret deploy-site-scout-private .ssh/id_ecdsa.site-scout-private

  cat <<- EOF >> .ssh/config

	Host site-scout-private
	HostName github.com
	IdentitiesOnly yes
	IdentityFile ~/.ssh/id_ecdsa.site-scout-private
	EOF

  # Checkout site-scout-private
  git-clone git@site-scout-private:MozillaSecurity/site-scout-private.git /src/site-scout-private
fi

update-ec2-status "Setup: fetching build"
build="$(python3 -c "import random;print(random.choice(['asan','debug','tsan','asan32','debug32']))")"
case $build in
  asan32)
    fuzzfetch -n build --fuzzing --asan --cpu x86
    ;;
  debug32)
    fuzzfetch -n build --fuzzing --debug --cpu x86
    ;;
  *)
    fuzzfetch -n build --fuzzing "--$build"
    ;;
esac

# setup reporter
python3 -m TaskStatusReporter --report-from-file status.txt --keep-reporting 60 &
# shellcheck disable=SC2064
trap "kill $!; python3 -m TaskStatusReporter --report-from-file status.txt" EXIT

update-ec2-status "Setup: launching site-scout"
yml="$(python3 -c "import pathlib,random;print(random.choice(list(pathlib.Path('/src/site-scout-private').glob('**/*.yml'))))")"
python3 -m site_scout ./build/firefox -i "$yml" --status-report status.txt --time-limit "$TIMELIMIT" --jobs "$JOBS" --fuzzmanager
