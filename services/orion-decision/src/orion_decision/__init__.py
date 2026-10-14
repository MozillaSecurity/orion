# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Decision module for Orion builds"""

import os
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from taskcluster.helper import TaskclusterConfig

TASKCLUSTER_ROOT_URL = os.getenv(
    "TASKCLUSTER_ROOT_URL", "https://community-tc.services.mozilla.com"
)
Taskcluster = TaskclusterConfig(TASKCLUSTER_ROOT_URL)

ARTIFACTS_EXPIRE = relativedelta(months=6)  # timedelta doesn't support months
DEADLINE = timedelta(days=1)
OWNER_EMAIL = "truber@mozilla.com"
PROVISIONER_ID = "proj-fuzzing"
SOURCE_URL = "https://github.com/MozillaSecurity/orion"
del os, relativedelta, timedelta, TaskclusterConfig
