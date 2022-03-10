# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.


import logging
from typing import List

from tcadmin.resources import Hook, WorkerPool

from ..common import taskcluster
from .pool import cancel_tasks

LOG = logging.getLogger(__name__)


async def cancel_pool_tasks(action: List[str], resource: WorkerPool) -> None:
    """Cancel all the tasks on a WorkerPool being updated or deleted"""
    assert isinstance(resource, WorkerPool)

    _, worker_type = resource.workerPoolId.split("/")
    cancel_tasks(worker_type)


async def trigger_hook(action: List[str], resource: WorkerPool) -> None:
    """Trigger a Hook after it is created or updated"""
    assert isinstance(resource, Hook)

    hooks = taskcluster.get_service("hooks")
    LOG.info(f"Triggering hook {resource.hookGroupId} / {resource.hookId}")
    hooks.triggerHook(resource.hookGroupId, resource.hookId, {})
