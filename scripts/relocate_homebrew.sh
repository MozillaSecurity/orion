#!/bin/sh -ex
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

[ -z "$HOMEBREW_PREFIX" ] && echo "Missing HOMEBREW_PREFIX" >&2 && exit 2

cd "$HOMEBREW_PREFIX"

relative_to () {
  file="$1"
  base="$2"
  perl -e 'use File::Spec; print File::Spec->abs2rel(@ARGV) . "\n"' "$file" "$base"
}

# Rewrite she-bang scripts that reference an interpreter in HOMEBREW_PREFIX to use /usr/bin/env
# shellcheck disable=SC2039,SC2046
find $(find . -name bin -type d) -type f -exec awk "FNR>1 {nextfile} /${HOMEBREW_PREFIX//\//\\/}/ { print FILENAME ; nextfile }" \{\} \+ | while read -r inp
do
  sed -E -i '' '1s,^#!(/[^/]+)*/([^/]+)$,#!/usr/bin/env \2,' "$inp"
done

# Make all Mach-O binaries load dylibs relative to themselves
find . -type f -exec file -h \{\} \+ | grep "Mach-O" | grep -v '(' | cut -d: -f1 | while read -r inp
do
  # preserve file permissions to restore later
  perm="$(stat -f %p "$inp")"
  # some files are installed read-only. ensure they are writable
  chmod +w "$inp"
  if ! file "$inp" | grep -q executable; then
    # change lib id to @rpath
    install_name_tool -id "@rpath/$(basename "$inp")" "$inp"
  fi
  # in both cases, make all loads relative to @loader_path
  otool -L "$inp" | tail -n +2 | cut -f 2 | cut -f1 -d\ | grep "$HOMEBREW_PREFIX" | while read -r lib
  do
    install_name_tool -change "$lib" "@loader_path/$(relative_to "$lib" "$PWD/$(dirname "$inp")")" "$inp"
  done
  # restore file permissions
  chmod "$perm" "$inp"
done
