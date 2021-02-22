#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

cd /recipes

# shellcheck source=recipes/linux/common.sh
source ./common.sh
sys-update

# if "supports-test" tag is found, run pre-test setup (if any)
{
  # shellcheck disable=SC2154
  ! grep -q supports-test "./${recipe}"
} || {
  echo "Running ${recipe} test pre-setup..." >&2
  "./${recipe}" test-setup
}

"./${recipe}"
./cleanup.sh

# either the "supports-test" tag isn't found, or the tests pass
{
  ! grep -q supports-test "./${recipe}"
} || {
  echo "Running ${recipe} tests..." >&2
  "./${recipe}" test
}
