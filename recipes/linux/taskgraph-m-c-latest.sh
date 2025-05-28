#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# shellcheck source=recipes/linux/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

#### Helpers for fetching toolchain artifacts from fxci

_TC_CACHE="/tmp/resolve-tc-cache"

_ensure-tc-taskgraph-data() {
  mkdir -p "$_TC_CACHE"
  if [[ ! -e "$_TC_CACHE/full-task-graph.json" ]]; then
    apt-install-auto \
      ca-certificates \
      curl
    retry-curl -o "$_TC_CACHE/full-task-graph.json" "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.v2.mozilla-central.latest.taskgraph.decision/artifacts/public/full-task-graph.json"
  fi
}

# resolve toolchain alias (eg. clang -> clang-16)
resolve-tc-alias() {
  _ensure-tc-taskgraph-data
  apt-install-auto python3
  python3 - "$_TC_CACHE/full-task-graph.json" "$1" <<-"EOF"
	import json
	import sys
	name=sys.argv[2]
	with open(sys.argv[1], "r") as fd:
	  data = json.load(fd)
	for tc, defn in data.items():
	  if not tc.startswith("toolchain-linux64-"):
	    continue
	  aliases = defn.get("attributes", {}).get("toolchain-alias", "")
	  if isinstance(aliases, str):
	    aliases = [aliases]
	  if f"linux64-{name}" in aliases:
	    print(tc.split("-", 2)[2])
	    break
	else:
	  print(f"No linux64-{name} toolchain found", file=sys.stderr)
	  sys.exit(1)
	EOF
}

# resolve toolchain artifact (eg. clang-17 -> public/build/clang.tar.zst)
resolve-tc-artifact() {
  _ensure-tc-taskgraph-data
  apt-install-auto python3
  python3 - "$_TC_CACHE/full-task-graph.json" "$1" <<-"EOF"
	import json
	import sys
	name=sys.argv[2]
	with open(sys.argv[1], "r") as fd:
	  data = json.load(fd)
	print(data[f"toolchain-linux64-{name}"]["attributes"]["toolchain-artifact"])
	EOF
}

# resolve toolchain source artifact (eg. clang-17 -> public/build/llvm-project.tar.zst)
resolve-tc-src-artifact() {
  _ensure-tc-taskgraph-data
  apt-install-auto python3
  python3 - "$_TC_CACHE/full-task-graph.json" "$1" <<-"EOF"
	import json
	import sys
	name=sys.argv[2]
	with open(sys.argv[1], "r") as fd:
	  data = json.load(fd)
	print(data[f"fetch-{name}"]["attributes"]["fetch-artifact"])
	EOF
}

# return the artifact url for a given toolchain alias (eg. grcov or clang)
resolve-tc() {
  _ensure-tc-taskgraph-data
  apt-install-auto python3
  python3 - "$_TC_CACHE/full-task-graph.json" "$1" <<-"EOF"
	import json
	import sys
	with open(sys.argv[1]) as fd:
	  data = json.load(fd)
	name = sys.argv[2]
	if f"toolchain-linux64-{name}" in data:
	  defn = data[f"toolchain-linux64-{name}"]
	else:
	  for tc, defn in data.items():
	    if not tc.startswith("toolchain-linux64-"):
	      continue
	    aliases = defn.get("attributes", {}).get("toolchain-alias", "")
	    if isinstance(aliases, str):
	      aliases = [aliases]
	    if f"linux64-{name}" in aliases:
	      break
	  else:
	    print(f"No linux64-{name} toolchain found", file=sys.stderr)
	    sys.exit(1)
	route = [rt for rt in defn["task"]["routes"] if ".hash." in rt][0]
	route = route.split(".", 1)[1]
	artifact = defn["attributes"]["toolchain-artifact"]
	print(f"https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/{route}/artifacts/{artifact}")
	EOF
}

# return the source artifact url for a given toolchain alias (eg. grcov or clang)
resolve-tc-src() {
  _ensure-tc-taskgraph-data
  apt-install-auto python3
  python3 - "$_TC_CACHE/full-task-graph.json" "$1" <<-"EOF"
	import json
	import sys
	with open(sys.argv[1]) as fd:
	  data = json.load(fd)
	name = sys.argv[2]
	if f"fetch-{name}" in data:
	  defn = data[f"fetch-{name}"]
	else:
	  for tc, defn in data.items():
	    if not tc.startswith("toolchain-linux64-"):
	      continue
	    aliases = defn.get("attributes", {}).get("toolchain-alias", "")
	    if isinstance(aliases, str):
	      aliases = [aliases]
	    if f"linux64-{name}" in aliases:
	      defn = data[f'fetch-{tc.split("-", 2)[2]}']
	      break
	  else:
	    print(f"No linux64-{name} toolchain found", file=sys.stderr)
	    sys.exit(1)
	route = [rt for rt in defn["task"]["routes"] if ".hash." in rt][0]
	route = route.split(".", 1)[1]
	artifact = defn["attributes"]["fetch-artifact"]
	print(f"https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/{route}/artifacts/{artifact}")
	EOF
}
