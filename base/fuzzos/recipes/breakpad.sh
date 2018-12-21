#!/usr/bin/env bash

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
