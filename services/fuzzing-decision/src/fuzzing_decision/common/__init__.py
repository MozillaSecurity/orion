# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.


import os

from taskcluster.helper import TaskclusterConfig

# Shared taskcluster configuration, defaulting to community-tc.
taskcluster = TaskclusterConfig(
    os.environ.get("TASKCLUSTER_ROOT_URL", "https://community-tc.services.mozilla.com")
)
