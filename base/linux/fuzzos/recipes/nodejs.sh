#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

#### Install NodeJS

curl -sL https://deb.nodesource.com/setup_10.x | bash -
apt-get install -y nodejs
