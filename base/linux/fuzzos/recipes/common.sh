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
function retry () {
  # shellcheck disable=SC2015
  for _ in {1..9}
  do
    "$@" && return || sleep 30
  done
  "$@"
}

# `apt-get update` command with retry functionality.
function sys-update () {
  retry apt-get update -qq
}

# `apt-get install` command with retry functionality.
function sys-embed () {
  retry apt-get install -y -qq --no-install-recommends --no-install-suggests "$@"
}

# Calls `apt-get install` on it's arguments but marks them as automatically installed.
# Previously installed packages are not affected.
function apt-install-auto () {
  new=()
  for pkg in "$@"; do
    if ! dpkg -l "$pkg" 2>&1 | grep -q ^ii; then
      new+=("$pkg")
    fi
  done
  sys-embed "${new[@]}"
  apt-mark auto "${new[@]}"
}

function get-latest-github-release () {
  # Bypass GitHub API RateLimit. Note that we do not follow the redirect.
  # shellcheck disable=SC2016
  retry curl -s "https://github.com/$1/releases/latest" | rg -Nor '$1' 'tag/(.+)"'
}

function git-clone () {
   retry git clone --depth 1 --no-tags "$1" "${2:-$(basename "$1")}"
}

# In a chrooted 32-bit environment "uname -m" would still return 64-bit.
function is-64-bit () {
  if [ "$(getconf LONG_BIT)" = "64" ];
  then
    true
  else
    false
  fi
}

function is-arm64 () {
  if [ "$(uname -i)" = "aarch64" ];
  then
    true
  else
    false
  fi
}

function is-amd64 () {
  if [ "$(uname -i)" = "x86_64" ];
  then
    true
  else
    false
  fi
}

# Curl with headers set for accessing GCE metadata service
function curl-gce {
  retry curl -H "Metadata-Flavor: Google" -s --connect-timeout 25 "$@"
}

# Determine the relative hostname based on the outside environment.
function relative-hostname {
  choice=${1,,}
  case $choice in
    ec2 | ec2spot)
      retry curl -s --connect-timeout 25 "$EC2_METADATA_URL/public-hostname" || :
      ;;
    gce)
      local IFS='.'
      # read external IP as an array of octets
      read -ra octets <<< "$(curl-gce "$GCE_METADATA_URL/instance/network-interfaces/0/access-configs/0/external-ip")"
      # reverse the array into "stetco"
      stetco=()
      for i in "${octets[@]}"; do
        stetco=("$i" "${stetco[@]}")
      done
      # output hostname
      echo "${stetco[*]}.bc.googleusercontent.com"
      ;;
    *)
      hostname -f
      ;;
  esac
}

# Add AWS credentials based on the given provider
function setup-aws-credentials {
  if [[ ! -f "$HOME/.aws/credentials" ]]
  then
    choice=${1,,}
    case $choice in
      gce)
        # Get AWS credentials for GCE to be able to read from Credstash
        mkdir -p "$HOME/.aws"
        retry berglas access fuzzmanager-cluster-secrets/credstash-aws-auth > "$HOME/.aws/credentials"
        chmod 0600 "$HOME/.aws/credentials"
        ;;
    esac
  fi
}

# Add relative hostname to the FuzzManager configuration.
function setup-fuzzmanager-hostname {
  name=$(relative-hostname "$1")
  if [ -z "$name" ]
  then
    echo "WARNING: hostname was not determined correctly."
    name=$(hostname -f)
  fi
  echo "Using '$name' as hostname."
  echo "clientid = $name" >> "$HOME/.fuzzmanagerconf"
}

# Disable AWS EC2 pool; suitable as trap function.
function disable-ec2-pool {
  if [[ -n $1 ]]
  then
    python3 -m EC2Reporter --disable "$1"
  fi
}

# Show sorted list of largest files and folders.
function size () {
  du -cha "$1" 2>/dev/null | sort -rh | head -n 100
}
