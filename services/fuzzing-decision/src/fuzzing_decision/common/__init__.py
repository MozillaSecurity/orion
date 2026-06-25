# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.


import os

from taskcluster.helper import TaskclusterConfig

# Keep the Taskcluster endpoint configurable for local and task environments.
taskcluster = TaskclusterConfig(
    os.environ.get("TASKCLUSTER_ROOT_URL", "https://firefox-ci-tc.services.mozilla.com")
)
