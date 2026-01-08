#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# disable core dumps
ulimit -c 0

# shellcheck source=recipes/linux/common.sh
source "$HOME/.local/bin/common.sh"

mkdir -p "$HOME/results/crashes"

if [[ -z $NO_SECRETS ]]; then
  # setup AWS credentials to use S3
  setup-aws-credentials

  # get gcp fuzzdata credentials
  mkdir -p ~/.config/gcloud
  get-tc-secret google-cloud-storage-guided-fuzzing ~/.config/gcloud/application_default_credentials.json raw
fi

fuzzilli-deadline() {
  if [[ -n $TASK_ID ]] || [[ -n $RUN_ID ]]; then
    echo "$(($(get-deadline) - $(date +%s) - 5 * 60))"
  else
    echo $((10 * 365 * 24 * 3600))
  fi
}

# Get the deploy key for fuzzilli from Taskcluster
if [[ $DIFFERENTIAL ]]; then
  get-tc-secret deploy-fuzzilli-differential "$HOME/.ssh/id_rsa.fuzzilli"

  # Setup Key Identities for private fuzzilli fork
  cat <<EOF >"$HOME/.ssh/config"

Host fuzzilli
Hostname github.com
IdentityFile "$HOME/.ssh/id_rsa.fuzzilli"
EOF

else
  get-tc-secret deploy-fuzzing-shells-private ~/.ssh/id_rsa.fuzzing-shells-private

  # Setup Key Identities for private overlay
  cat >>~/.ssh/config <<EOF

Host fuzzing-shells-private
Hostname github.com
IdentityFile "$HOME/.ssh/id_rsa.fuzzing-shells-private"
EOF

fi

# -----------------------------------------------------------------------------

cd "$HOME"

# Download our build
if [[ $DIFFERENTIAL ]]; then
  git-clone git@fuzzilli:MozillaSecurity/fuzzilli-differential.git fuzzilli
else
  git-clone https://github.com/googleprojectzero/fuzzilli fuzzilli
  git-clone git@fuzzing-shells-private:MozillaSecurity/fuzzing-shells-private.git

  rsync -rv --progress fuzzing-shells-private/fuzzilli/ fuzzilli/

  if compgen -G "fuzzilli/*.patch" >/dev/null; then
    cd fuzzilli
    git apply ./*.patch
    cd ..
  fi
fi

for r in fuzzfetch fuzzmanager guided-fuzzing-daemon; do
  pushd "/srv/repos/$r" >/dev/null
  retry git fetch origin HEAD
  git reset --hard FETCH_HEAD
  popd >/dev/null
done

get-tc-secret fuzzmanagerconf "$HOME/.fuzzmanagerconf"
cat >>"$HOME/.fuzzmanagerconf" <<EOF
sigdir = $HOME/signatures
tool = ${TOOLNAME-Fuzzilli}
EOF

if [[ -n $TASKCLUSTER_ROOT_URL ]] && [[ -n $TASK_ID ]]; then
  echo "clientid = task-${TASK_ID}-run-${RUN_ID}"
elif [[ -n $EC2SPOTMANAGER_POOLID ]]; then
  echo "clientid = $(retry-curl http://169.254.169.254/latest/meta-data/public-hostname)"
else
  echo "clientid = ${CLIENT_ID-$(uname -n)}"
fi >>"$HOME/.fuzzmanagerconf"

# Download our build
if [[ $COVERAGE ]]; then
  retry fuzzfetch --target js --coverage -n build
else
  retry fuzzfetch --target js --debug --fuzzilli -n build
fi

cd fuzzilli
chmod +x mozilla/*.sh

source "$HOME/.local/share/swiftly/env.sh"

echo "$PATH"

if [[ -n $TASK_ID ]] || [[ -n $RUN_ID ]]; then
  task-status-reporter --report-from-file ./stats --keep-reporting 60 --random-offset 30 &

  onexit() {
    # ensure final stats are complete
    if [[ -e ./stats ]]; then
      task-status-reporter --report-from-file ./stats
    fi
  }
  trap onexit EXIT
fi

args=(
  --instances "${INSTANCES:-$(python3 -c 'import os;print(len(os.sched_getaffinity(0))//2)')}"
  --project "$S3_PROJECT"
  --stats ./stats
)

if [[ -n $USE_GCS ]]; then
  args+=(
    --bucket guided-fuzzing-data
    --provider GCS
  )
else
  args+=(
    --bucket mozilla-aflfuzz
  )
fi

if [[ -n $DIFFERENTIAL ]]; then
  args+=(--differential)
fi

if [[ -n $WASM ]]; then
  args+=(--wasm)
fi

if [[ -n $FAST_TIMEOUT ]]; then
  args+=(--timeout=250)
else
  args+=(--timeout=2000)
fi

if [[ -n $S3_CORPUS_REFRESH ]]; then
  mkdir work
  timeout -s 2 "$(fuzzilli-deadline)" guided-fuzzing-daemon --fuzzilli --debug --corpus-refresh work "${args[@]}" --build-dir ~/fuzzilli "$HOME/build/dist/bin/js" || true
else
  mkdir -p "$HOME/results/corpus"

  # Download corpus
  guided-fuzzing-daemon --debug --corpus-download "$HOME/results/corpus" "${args[@]}"

  # Download another corpus into ours
  if [[ -n $S3_PROJECT_EXTRA ]]; then
    guided-fuzzing-daemon --debug --corpus-download "$HOME/results/corpus" --bucket mozilla-aflfuzz --project "$S3_PROJECT_EXTRA"
  fi

  if [[ -z $DIFFERENTIAL ]]; then
    args+=(--queue-upload)
  fi

  if [[ $COVERAGE ]]; then
    timeout -s 2 "$(fuzzilli-deadline)" "$HOME/coverage.sh" "$HOME/build/dist/bin/js" "$HOME/build/"
  else
    guided-fuzzing-daemon "${args[@]}" --debug --fuzzilli --fuzzmanager --max-runtime "$(fuzzilli-deadline)" --build-dir ~/fuzzilli --corpus-out "$HOME/results" "$HOME/build/dist/bin/js"
  fi
fi
