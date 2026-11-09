== Orion Decision ==

Orion Decision loads the repository's service graph, plans affected work, and runs
the GitHub Actions plan, build, and Taskcluster publication commands. The checked-in
`.github/workflows/orion.yml` is generated from tracked service definitions, Dockerfiles,
service inputs, and recipes. Regenerate it with:

```sh
cd services/orion-decision
tox -e gha-workflow
```

The pre-commit hook rewrites the generated workflow. CI checks that the committed
workflow matches the service graph. Protect `master` with the required status check
**Orion workflow result**.

GitHub Actions runs pull requests, pushes to `master`, a Monday 05:00 UTC expiry
check, and manual runs. Manual runs accept comma-separated service names in
`force_services`. Pull requests build and test the head commit without publication
credentials. Successful `master` runs push architecture images and a combined Docker
`latest` manifest, then import per-architecture Docker archives and native archives
into FXCI's Taskcluster artifact and index routes. An older run cannot be rerun
for publication after a newer eligible `master` run; start a new manual run and select
or force the services that still need publication.

Windows 2025 runners use their preinstalled MSYS2 `bsdtar` only to extract the
downloaded bootstrap archive; native builds then use that downloaded MSYS2 runtime.

Configure the `dockerhub` GitHub environment with variable `DOCKERHUB_USERNAME` and
secret `DOCKERHUB_TOKEN`.

Set the repository variable `ORION_TASKCLUSTER_ROOT_URL` to
`https://firefox-ci-tc.services.mozilla.com`. The planner and dependency preparation
use this public endpoint for publication baselines, expiry checks, and unchanged
service archives. This Orion-specific variable does not change the Taskcluster
environment used by recipes or by the services themselves.

Create the `fxci` GitHub environment with variable `TASKCLUSTER_ROOT_URL` set to
`https://firefox-ci-tc.services.mozilla.com` and these secrets:

| Secret | FXCI client |
| --- | --- |
| `TASKCLUSTER_CI_WORKER_ORION_GHA_ACCESS_TOKEN` | `project/fuzzing/ci-worker-orion-gha` |
| `TASKCLUSTER_GH_ORION_PUBLISHER_ACCESS_TOKEN` | `project/fuzzing/gh-orion-publisher` |

These must be credentials issued by FXCI, rather than the existing Community TC
credentials. The worker client needs the matching FXCI worker identity and pool roles:

```text
assume:worker-id:proj-fuzzing/gh-orion-publish-*
assume:worker-pool:proj-fuzzing/orion-gha-publish
```

The publisher client creates tasks for scheduler `fuzzing` and queue
`proj-fuzzing/orion-gha-publish`. Task creation uses the default project
`none`, which the deployment's anonymous role authorizes. No explicit project
creation scope is needed. The client needs:

```text
queue:create-task:highest:proj-fuzzing/orion-gha-publish
queue:scheduler-id:fuzzing
queue:route:index.project.fuzzing.orion.*
```

The highest-priority creation scope also authorizes lower-priority imports. Tasks
delegate no additional scopes; resolution, reclaim, and artifact uploads use the
claimed task's credentials. The worker identity/pool roles must exist or be covered
by FXCI's matching role patterns.

GHA creates a root task directly for every eligible push, scheduled run, or manual
run. All imports and publication receipts share its task group. A retry reuses the
same root, while import IDs identify the individual attempt. No Taskcluster GitHub
integration or `.taskcluster.yml` decision is needed. The two GHA-hosted workers
serve this FXCI queue until submissions close and all submitted tasks settle.

Optional `fxci` environment variables `TASKCLUSTER_WST_AUDIENCE` and
`TASKCLUSTER_WST_SERVER_URL` configure an FXCI websocktunnel for live logs. Leave
both unset to disable the tunnel; normal task log artifacts are still uploaded.

The workflow's `GITHUB_TOKEN` has Actions artifact read access and contents read
access. The worker writes that token to a mode-0600 file for import tasks and strips
the raw credential from generic-worker's environment and logs. Import task IDs bind
the repository, revision, workflow run, attempt, and exact artifact. A failed-job-only
workflow rerun without a full set of attempt artifacts stops with instructions to
rerun all jobs.

Disable the old external Taskcluster Orion expiry cron hook when enabling this
workflow; otherwise both schedulers may rebuild expiring environments. The legacy
hook is external deployment configuration and is not changed by this repository.
Disable Orion's old Community TC GitHub integration when applying this cutover;
GHA now submits the complete FXCI publication graph directly.
