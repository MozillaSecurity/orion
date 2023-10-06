#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# shellcheck source=recipes/linux/common.sh
source "$(dirname "${BASH_SOURCE%/*}")/common.sh"

#### Helpers for fetching toolchain artifacts from fxci

_TC_CACHE="/tmp/resolve-tc-cache"

_ensure-tc-venv () {
  # Use a venv to install yaml so that python3-yaml doesn't prevent other
  #   pip installed packages from pulling yaml from pypi.
  # There have been issues with yaml versioning
  apt-install-auto python3-venv

  if [[ ! -d "$_TC_CACHE/venv" ]]; then
    python3 -m venv "$_TC_CACHE/venv"
    retry "$_TC_CACHE/venv/bin/python" -m pip install pyyaml
  fi >/dev/null
}

_ensure-tc-taskgraph-data () {
  apt-install-auto \
    ca-certificates \
    curl

  if [[ ! -e "$_TC_CACHE/label-to-taskid.json" ]]; then
    mkdir -p "$_TC_CACHE"
    retry-curl -o "$_TC_CACHE/label-to-taskid.json" "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.v2.mozilla-central.latest.taskgraph.decision/artifacts/public/label-to-taskid.json"
  fi
}

is-taskgraph-label () {
  _ensure-tc-taskgraph-data
  apt-install-auto python3
  python3 - "$_TC_CACHE/label-to-taskid.json" "$1" <<- "EOF"
	import json
	import sys
	with open(sys.argv[1]) as fd:
	  label_to_task = json.load(fd)
	sys.exit(f"{sys.argv[2]}" not in label_to_task)
EOF
}

# resolve toolchain alias (eg. clang -> clang-16)
resolve-tc-alias () {
  apt-install-auto \
    ca-certificates \
    curl

  _ensure-tc-venv
  if [[ ! -e "$_TC_CACHE/$1.yml" ]]; then
    mkdir -p "$_TC_CACHE"
    retry-curl -o "$_TC_CACHE/$1.yml" "https://hg.mozilla.org/mozilla-central/raw-file/tip/taskcluster/ci/toolchain/$1.yml"
  fi
  "$_TC_CACHE/venv/bin/python" - "$_TC_CACHE/$1.yml" "$1" <<- "EOF"
	import yaml
	import sys
	inp=sys.argv[1]
	name=sys.argv[2]
	with open(inp, "r") as fd:
	  data = yaml.load(fd, Loader=yaml.CLoader)
	for tc, defn in data.items():
	  alias = defn.get("run", {}).get("toolchain-alias", {})
	  if isinstance(alias, dict):
	    alias = alias.get("by-project", {}).get("default")
	  if alias == f"linux64-{name}":
	    print(tc.split("-", 1)[1])
	    break
	else:
	  raise Exception(f"No linux64-{name} toolchain found")
	EOF
}

# resolve toolchain artifact (eg. clang -> public/build/clang.tar.zst)
resolve-tc-artifact () {
  apt-install-auto \
    ca-certificates \
    curl

  _ensure-tc-venv
  if [[ ! -e "$_TC_CACHE/$1.yml" ]]; then
    mkdir -p "$_TC_CACHE"
    retry-curl -o "$_TC_CACHE/$1.yml" "https://hg.mozilla.org/mozilla-central/raw-file/tip/taskcluster/ci/toolchain/$1.yml"
  fi
  "$_TC_CACHE/venv/bin/python" - "$_TC_CACHE/$1.yml" "$2" <<- "EOF"
	import yaml
	import sys
	inp=sys.argv[1]
	name=sys.argv[2]
	with open(inp, "r") as fd:
	  data = yaml.load(fd, Loader=yaml.CLoader)
	if "toolchain-artifact" in data[f"linux64-{name}"].get("run", {}):
	  print(data[f"linux64-{name}"]["run"]["toolchain-artifact"])
	else:
	  print(data["job-defaults"]["run"]["toolchain-artifact"])
	EOF
}

# resolve toolchain source artifact (eg. clang-17 -> public/build/llvm-project.tar.zst)
resolve-tc-src-artifact () {
  apt-install-auto \
    ca-certificates \
    curl

  _ensure-tc-venv
  if [[ ! -e "$_TC_CACHE/toolchains.yml" ]]; then
    mkdir -p "$_TC_CACHE"
    retry-curl -o "$_TC_CACHE/toolchains.yml" "https://hg.mozilla.org/mozilla-central/raw-file/tip/taskcluster/ci/fetch/toolchains.yml"
  fi
  "$_TC_CACHE/venv/bin/python" - "$_TC_CACHE/toolchains.yml" "$1" <<- "EOF"
	import yaml
	import os.path
	import sys
	inp=sys.argv[1]
	name=sys.argv[2]
	with open(inp, "r") as fd:
	  data = yaml.load(fd, Loader=yaml.CLoader)
	fetch = data[name]["fetch"]
	if "artifact-name" in fetch:
	  print(f'public/{fetch["artifact-name"]}')
	else:
	  print(f'public/{os.path.basename(fetch["repo"])}.tar.zst')
	EOF
}

# return the artifact url for a given toolchain alias (eg. grcov or clang)
resolve-tc () {
  local artifact label
  _ensure-tc-taskgraph-data
  apt-install-auto python3
  if is-taskgraph-label "toolchain-linux64-$1"; then
    label="$1"
    artifact="public/build/$1.tar.zst"
  else
    label="$(resolve-tc-alias "$1")"
    artifact="$(resolve-tc-artifact "$1" "$label")"
  fi
  python3 - "$_TC_CACHE/label-to-taskid.json" "$label" "$artifact" <<- "EOF"
	import json
	import sys
	with open(sys.argv[1]) as fd:
	  label_to_task = json.load(fd)
	task_id = label_to_task[f"toolchain-linux64-{sys.argv[2]}"]
	print(f"https://firefox-ci-tc.services.mozilla.com/api/queue/v1/task/{task_id}/artifacts/{sys.argv[3]}")
EOF
}

# return the source artifact url for a given toolchain alias (eg. grcov or clang)
resolve-tc-src () {
  local artifact label
  _ensure-tc-taskgraph-data
  apt-install-auto python3
  if is-taskgraph-label "fetch-$1"; then
    label="$1"
  else
    label="$(resolve-tc-alias "$1")"
  fi
  artifact="$(resolve-tc-src-artifact "$label")"
  python3 - "$_TC_CACHE/label-to-taskid.json" "$label" "$artifact" <<- "EOF"
	import json
	import sys
	with open(sys.argv[1]) as fd:
	  label_to_task = json.load(fd)
	task_id = label_to_task[f"fetch-{sys.argv[2]}"]
	print(f"https://firefox-ci-tc.services.mozilla.com/api/queue/v1/task/{task_id}/artifacts/{sys.argv[3]}")
EOF
}
