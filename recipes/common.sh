#!/bin/bash -ex

# Calls `apt-get install` on it's arguments but marks them as automatically installed
# previously installed packages are not affected.
apt-install-auto () {
  new=()
  for pkg in "$@"; do
    if ! dpkg -l "$pkg" 2>&1 | grep -q ^ii; then
      new+=("$pkg")
    fi
  done
  apt-get -y -qq --no-install-recommends --no-install-suggests install "${new[@]}"
  apt-mark auto "${new[@]}"
}
