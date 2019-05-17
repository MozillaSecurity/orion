#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x

#### Install Berglas secrets management tool for GCP
# https://github.com/GoogleCloudPlatform/berglas

curl -L https://storage.googleapis.com/berglas/master/linux_amd64/berglas -o /usr/local/bin/berglas
chmod +x /usr/local/bin/berglas
