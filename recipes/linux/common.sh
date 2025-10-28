#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

##############################################################################
# NOTE: This is shared resource file which is added and sourced in `.bashrc`.
# You need to manually source it if you want to use it in any build recipe.
##############################################################################

# Constants
EC2_METADATA_URL="http://169.254.169.254/latest/meta-data"
GCE_METADATA_URL="http://169.254.169.254/computeMetadata/v1"

# Re-tries a certain command 9 times with a 30 seconds pause between each try.
function retry() {
  local op
  op="$(mktemp)"
  for _ in {1..9}; do
    if "$@" >"$op"; then
      cat "$op"
      rm "$op"
      return
    fi
    sleep 30
  done
  rm "$op"
  "$@"
}

# `apt-get update` command with retry functionality.
# shellcheck disable=SC2120
function sys-update() {
  if [[ $# -gt 0 ]]; then
    echo "usage: $0" >&2
    return 1
  fi
  retry apt-get update -qq
}

# `apt-get install` command with retry functionality.
function sys-embed() {
  retry apt-get install -y -qq --no-install-recommends --no-install-suggests "$@" >&2
}

# `apt-get install` dependencies without installing the package itself
function apt-install-depends() {
  local dep new pkg
  new=()
  for pkg in "$@"; do
    for dep in $(apt-get install -s "$pkg" | sed -n -e "/^Inst $pkg /d" -e 's/^Inst \([^ ]\+\) .*$/\1/p'); do
      new+=("$dep")
    done
  done
  sys-embed "${new[@]}"
}

# Calls `apt-get install` on it's arguments but marks them as automatically installed.
# Previously installed packages are not affected.
function apt-install-auto() {
  local new pkg
  new=()
  for pkg in "$@"; do
    if ! dpkg -l "$pkg" 2>&1 | grep -q ^ii; then
      new+=("$pkg")
    fi
  done
  if [[ ${#new[@]} -ne 0 ]]; then
    sys-embed "${new[@]}"
    apt-mark auto "${new[@]}" >&2
  fi
}

# Follow redirects and resolve a url
function resolve-url() {
  curl --connect-timeout 25 --fail --location --retry 5 --show-error --silent --head --write-out "%{url_effective}" "$@" -o /dev/null
}

# wrap curl with sane defaults
function retry-curl() {
  curl --connect-timeout 25 --fail --location --retry 5 --retry-all-errors --show-error --silent --write-out "%{stderr}[downloaded %{url_effective}]\n" "$@"
}

function get-deadline() {
  if [[ -z $TASK_ID ]] || [[ -z $RUN_ID ]]; then
    echo "error: get-deadline() is only supported on Taskcluster" >&2
    exit 1
  fi
  tmp="$(mktemp -d)"
  retry taskcluster api queue task "$TASK_ID" >"$tmp/task.json"
  retry taskcluster api queue status "$TASK_ID" >"$tmp/status.json"
  deadline="$(date --date "$(jshon -e status -e deadline -u <"$tmp/status.json")" +%s)"
  started="$(date --date "$(jshon -e status -e runs -e "$RUN_ID" -e started -u <"$tmp/status.json")" +%s)"
  max_run_time="$(jshon -e payload -e maxRunTime -u <"$tmp/task.json")"
  rm -rf "$tmp"
  run_end="$((started + max_run_time))"
  if [[ $run_end -lt $deadline ]]; then
    echo "$run_end"
  else
    echo "$deadline"
  fi
}

# Get the task deadline.
# If running locally, return a date far in the future to prevent expiration.
function get-target-time() {
  local remaining_time result
  if [[ -n $TASK_ID ]] || [[ -n $RUN_ID ]]; then
    remaining_time=$(($(get-deadline) - $(date +%s)))
  else
    remaining_time=$((10 * 365 * 24 * 3600))
  fi
  if [[ ${COVERAGE-0} == 1 ]] && [[ ${COVRUNTIME-0} -gt 0 ]]; then
    result=$COVRUNTIME
    if [[ $result -gt $remaining_time ]]; then
      echo "error: not enough time to respect COVRUNTIME, failing..." >&2
      exit 1
    fi
  elif [[ $TARGET_TIME =~ ^-?[0-9]+$ ]]; then
    result=$TARGET_TIME
    if [[ $result -gt $remaining_time ]]; then
      echo "warning: TARGET_TIME given, but exceeds task deadline!" >&2
    fi
  else
    if [[ $remaining_time -lt $((5 * 60)) ]]; then
      echo "warning: less than 5 minutes remains before task deadline!" >&2
    fi
    result=$((remaining_time - 5 * 60))
  fi
  echo "$result"
}

function get-latest-github-release() {
  if [[ $# -ne 1 ]]; then
    echo "usage: $0 repo" >&2
    return 1
  fi
  # Bypass GitHub API RateLimit. Note that we do not follow the redirect.
  retry-curl --head --no-location "https://github.com/$1/releases/latest" | grep ^location | sed 's/.\+\/tag\/\(.\+\)[[:space:]]\+/\1/'
}

# Shallow git-clone of the default branch only
function git-clone() {
  local dest url
  if [[ $# -lt 1 ]] || [[ $# -gt 2 ]]; then
    echo "usage: $0 url [name]" >&2
    return 1
  fi
  url="$1"
  if [[ $# -eq 2 ]]; then
    dest="$2"
  else
    dest="$(basename "$1" .git)"
  fi
  git init "$dest"
  pushd "$dest" >/dev/null || return 1
  git remote add origin "$url"
  retry git fetch -q --depth 1 --no-tags origin HEAD
  git -c advice.detachedHead=false checkout FETCH_HEAD
  popd >/dev/null || return 1
}

# In a chrooted 32-bit environment "uname -m" would still return 64-bit.
# shellcheck disable=SC2120
function is-64-bit() {
  if [[ $# -gt 0 ]]; then
    echo "usage: $0" >&2
    return 1
  fi
  if [[ "$(getconf LONG_BIT)" == "64" ]]; then
    true
  else
    false
  fi
}

# shellcheck disable=SC2120
function is-arm64() {
  if [[ $# -gt 0 ]]; then
    echo "usage: $0" >&2
    return 1
  fi
  if [[ "$(uname -m)" == "aarch64" ]]; then
    true
  else
    false
  fi
}

# shellcheck disable=SC2120
function is-amd64() {
  if [[ $# -gt 0 ]]; then
    echo "usage: $0" >&2
    return 1
  fi
  if [[ "$(uname -m)" == "x86_64" ]]; then
    true
  else
    false
  fi
}

# Curl with headers set for accessing GCE metadata service
function curl-gce() {
  retry-curl -H "Metadata-Flavor: Google" "$@"
}

# Determine the relative hostname based on the outside environment.
# shellcheck disable=SC2120
function relative-hostname() {
  if [[ $# -gt 0 ]]; then
    echo "usage: $0" >&2
    return 1
  fi
  case "$(echo "${SHIP-$(get-provider)}" | tr "[:upper:]" "[:lower:]")" in
    ec2 | ec2spot)
      retry-curl "$EC2_METADATA_URL/public-hostname" || :
      ;;
    gce)
      local IFS='.'
      # read external IP as an array of octets
      read -ra octets <<<"$(curl-gce "$GCE_METADATA_URL/instance/network-interfaces/0/access-configs/0/external-ip")"
      # reverse the array into "stetco"
      local stetco=()
      for i in "${octets[@]}"; do
        stetco=("$i" "${stetco[@]}")
      done
      # output hostname
      echo "${stetco[*]}.bc.googleusercontent.com"
      ;;
    taskcluster)
      echo "task-${TASK_ID}-run-${RUN_ID}"
      ;;
    *)
      hostname -f
      ;;
  esac
}

# Get a secret from Taskcluster 'secret' service
function get-tc-secret() {
  local nofile output raw secret
  if [[ $# -lt 1 ]] || [[ $# -gt 3 ]]; then
    echo "usage: get-tc-secret name [output] [raw]" >&2
    return 1
  fi
  secret="$1"
  if [[ $# -eq 1 ]] || [[ $2 == "-" ]]; then
    output=/dev/stdout
    nofile=1
  else
    output="$2"
    nofile=0
  fi
  raw=0
  if [[ $# -eq 3 ]]; then
    if [[ $3 == "raw" ]]; then
      raw=1
    else
      echo "unknown arg: $3" >&2
      return 1
    fi
  fi
  if [[ $nofile -eq 0 ]]; then
    mkdir -p "$(dirname "$output")"
  fi
  if [[ -x "/usr/local/bin/taskcluster" ]]; then
    TASKCLUSTER_ROOT_URL="${TASKCLUSTER_PROXY_URL-$TASKCLUSTER_ROOT_URL}" retry taskcluster api secrets get "project/fuzzing/$secret"
  elif [[ -n $TASKCLUSTER_PROXY_URL ]]; then
    retry-curl "$TASKCLUSTER_PROXY_URL/secrets/v1/secret/project/fuzzing/$secret"
  else
    echo "error: either taskcluster client binary must be installed or TASKCLUSTER_PROXY_URL must be set" >&2
    return 1
  fi | if [[ $raw -eq 1 ]]; then
    jshon -e secret -e key
  else
    jshon -e secret -e key -u
  fi >"$output"
  if [[ $nofile -eq 0 ]]; then
    chmod 0600 "$output"
  fi
}

# Add AWS credentials based on the given provider
# shellcheck disable=SC2120
function setup-aws-credentials() {
  if [[ $# -gt 0 ]]; then
    echo "usage: $0" >&2
    return 1
  fi
  if [[ ! -f "$HOME/.aws/credentials" ]]; then
    case "$(echo "${SHIP-$(get-provider)}" | tr "[:upper:]" "[:lower:]")" in
      gce)
        # Get AWS credentials for GCE to be able to read from Credstash
        mkdir -p "$HOME/.aws"
        retry berglas access fuzzmanager-cluster-secrets/credstash-aws-auth >"$HOME/.aws/credentials"
        chmod 0600 "$HOME/.aws/credentials"
        ;;
      taskcluster)
        # Get AWS credentials for TC to be able to read from Credstash
        mkdir -p "$HOME/.aws"
        if [[ -x "/usr/local/bin/taskcluster" ]]; then
          TASKCLUSTER_ROOT_URL="${TASKCLUSTER_PROXY_URL-$TASKCLUSTER_ROOT_URL}" retry taskcluster api secrets get "project/fuzzing/${CREDSTASH_SECRET}"
        else
          retry-curl "$TASKCLUSTER_PROXY_URL/secrets/v1/secret/project/fuzzing/${CREDSTASH_SECRET}"
        fi | jshon -e secret -e key -u >"$HOME/.aws/credentials"
        chmod 0600 "$HOME/.aws/credentials"
        ;;
    esac
  fi
}

# Determine the provider environment we're running in
# shellcheck disable=SC2120
function get-provider() {
  if [[ $# -gt 0 ]]; then
    echo "usage: $0" >&2
    return 1
  fi
  case "$EC2SPOTMANAGER_PROVIDER" in
    EC2Spot)
      echo "EC2"
      return 0
      ;;
    GCE)
      echo "GCE"
      return 0
      ;;
    *)
      if [[ -n $TASKCLUSTER_ROOT_URL ]]; then
        echo "Taskcluster"
        return 0
      fi
      ;;
  esac
  echo "Unable to determine provider!" >&2
  return 1
}

# Add relative hostname to the FuzzManager configuration.
# shellcheck disable=SC2120
function setup-fuzzmanager-hostname() {
  if [[ $# -gt 0 ]]; then
    echo "usage: $0" >&2
    return 1
  fi
  local name
  name="$(relative-hostname)"
  if [[ -z $name ]]; then
    echo "WARNING: hostname was not determined correctly." >&2
    name="$(hostname -f)"
  fi
  echo "Using '$name' as hostname." >&2
  echo "clientid = $name" >>"$HOME/.fuzzmanagerconf"
}

# Disable AWS EC2 pool; suitable as trap function.
# shellcheck disable=SC2120
function disable-ec2-pool() {
  if [[ $# -gt 0 ]]; then
    echo "usage: $0" >&2
    return 1
  fi
  if [[ -n $EC2SPOTMANAGER_POOLID ]]; then
    echo "Disabling EC2 pool $EC2SPOTMANAGER_POOLID" >&2
    ec2-reporter --disable "$EC2SPOTMANAGER_POOLID"
  fi
}

# Include timestamp in status message.
function update-status() {
  if [[ -n $TASKCLUSTER_FUZZING_POOL ]] || [[ -n $EC2SPOTMANAGER_POOLID ]]; then
    if [[ ! -e "$HOME/.fuzzmanagerconf" ]]; then
      echo "WARNING: fuzzmanagerconf not present, can't report task status" >&2
      return 0
    fi
  fi
  update-ec2-status "[$(date -Is)] $*" || true
}

function update-ec2-status() {
  if [[ -n $EC2SPOTMANAGER_POOLID ]]; then
    ec2-reporter --report "$@"
  elif [[ -n $TASKCLUSTER_FUZZING_POOL ]]; then
    task-status-reporter --report "$@"
  fi
}

# Show sorted list of largest files and folders.
function size() {
  du -cha "$@" 2>/dev/null | sort -rh | head -n 100
}

function install-apt-key() {
  local keyurl
  if [[ $# -ne 1 ]]; then
    echo "usage: $0 keyurl" >&2
    return 1
  fi
  keyurl="$1"

  fn="${keyurl##*/}"
  base="${fn%%.*}"
  output="/etc/apt/keyrings/${base}.gpg"

  mkdir -p /etc/apt/keyrings ~/.gnupg
  TMPD="$(mktemp -d -p. aptkey.XXXXXXXXXX)"
  retry-curl "$keyurl" -o "$TMPD/aptkey.key"
  gpg --no-default-keyring --trustdb-name "$TMPD/trustdb.gpg" --keyring "$TMPD/tmp.gpg" --import "$TMPD/aptkey.key"
  gpg --no-default-keyring --trustdb-name "$TMPD/trustdb.gpg" --keyring "$TMPD/tmp.gpg" --export --output "$output"
  rm -rf "$TMPD"
  echo "$output"
}
