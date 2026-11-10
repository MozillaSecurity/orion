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
into Taskcluster's existing artifact and index routes. A failed-job-only rerun can reuse
the newest live build artifact for each exact service and architecture from an earlier
attempt of the same run. New Taskcluster tasks keep the current attempt's publication
rank and provenance. Import tasks retain the source artifact ID and digest; receipts and
monitor control reference the actual producer task IDs. Expired or missing artifacts
still require rerunning the relevant build job. Re-running all jobs is required when
the current attempt has no active Taskcluster worker pool. An older run cannot publish
after a newer eligible `master` run; start a new manual run and select or force the
services that still need publication.

Windows 2025 runners use their preinstalled MSYS2 `bsdtar` only to extract the
downloaded bootstrap archive; native builds then use that downloaded MSYS2 runtime.

Configure the `dockerhub` GitHub environment with variable `DOCKERHUB_USERNAME` and
secret `DOCKERHUB_TOKEN`. Configure the `communitytc` GitHub environment with
variable `TASKCLUSTER_ROOT_URL` set to
`https://community-tc.services.mozilla.com`, and secrets
`TASKCLUSTER_CI_WORKER_ORION_GHA_ACCESS_TOKEN` for worker client
`project/fuzzing/ci-worker-orion-gha`, which needs
`assume:worker-id:proj-fuzzing/gh-orion-publish-*` and
`assume:worker-pool:proj-fuzzing/orion-gha-publish` and
`TASKCLUSTER_GH_ORION_PUBLISHER_ACCESS_TOKEN` for publisher client
`project/fuzzing/gh-orion-publisher`, which the GHA job uses to create import
tasks and needs
`queue:create-task:highest:proj-fuzzing/orion-gha-publish`,
`queue:create-task:project:none`, `queue:scheduler-id:taskcluster-github`, and
`queue:route:index.project.fuzzing.orion.*`. Task resolution and reclaim use the
claimed task's task credentials. The `.taskcluster.yml` decision role needs the
same task-creation scopes.

The workflow's `GITHUB_TOKEN` has Actions artifact read access and contents read
access. The worker writes that token to a mode-0600 file for import tasks and strips
the raw credential from generic-worker's environment and logs. Import task metadata
binds the repository, revision, workflow run, current attempt, and exact source artifact.

Disable the old external Taskcluster Orion expiry cron hook when enabling this
workflow; otherwise both schedulers may rebuild expiring environments. The legacy
hook is external deployment configuration and is not changed by this repository.
