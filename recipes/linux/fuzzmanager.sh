#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Install FuzzManager

cd "$HOME"

git-clone https://github.com/mozillasecurity/fuzzmanager
pip3 install ./fuzzmanager
pip3 install boto
