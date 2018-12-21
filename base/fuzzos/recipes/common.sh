#!/usr/bin/env bash

# NOTE
# This is shared resource file and is added and sourced in `.bashrc`.
# You need to manually source it if you want to use it in any build recipe.

# Constants
EC2_METADATA_URL="http://169.254.169.254/latest/meta-data"

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
    retry apt-get install -y -qq --no-install-recommends --no-install-suggests @$
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
  apt-get -y -qq --no-install-recommends --no-install-suggests install "${new[@]}"
  apt-mark auto "${new[@]}"
}

function get-latest-github-release () {
  # Bypass GitHub API RateLimit. Note that we do not follow the redirect.
  # shellcheck disable=SC2016
  retry curl -s "https://github.com/$1/releases/latest" | rg -Nor '$1' 'tag/(.+)"'
}

# In a chrooted 32-bit environment "uname -m" would still return 64-bit.
function is-64-bit () {
  if [ "$(getconf LONG_BIT)" = "64" ];
  then
    echo true
  else
    echo false
  fi
}

# Determine the relative hostname based on the outside environment.
function relative-hostname {
  choice=${1,,}
  case $choice in
    ec2)
      retry curl -s --connect-timeout 25 "$EC2_METADATA_URL/public-hostname" || :
      ;;
    *)
      hostname
      ;;
  esac
}

# Add relative hostname to the FuzzManager configuration.
function setup-fuzzmanager-hostname {
  name=$(relative-hostname "$1")
  if [ -z "$name" ]
  then
    echo "WARNING: hostname was not determined correctly."
    name=$(hostname)
  fi
  echo "Using '$name' as hostname."
  echo "clientid = $name" >> "$HOME/.fuzzmanagerconf"
}

