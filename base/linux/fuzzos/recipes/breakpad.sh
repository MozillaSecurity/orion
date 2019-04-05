#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

#### Install Breakpad Tools
# https://developer.mozilla.org/en-US/docs/Mozilla/Debugging/Debugging_a_minidump#Using_other_tools_to_inspect_minidump_data

TMPD="$(mktemp -d -p. breakpad.tools.XXXXXXXXXX)"
( cd "$TMPD"
  curl -LO https://s3.amazonaws.com/getsentry-builds/getsentry/breakpad-tools/breakpad-tools-linux.zip
  unzip -j breakpad-tools-linux.zip minidump_stackwalk -d /usr/local/bin/
)

rm -rf "$TMPD"
