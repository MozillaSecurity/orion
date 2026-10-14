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
into Taskcluster's existing artifact and index routes. An older run cannot be rerun
for publication after a newer eligible `master` run; start a new manual run and select
or force the services that still need publication.

Windows 2025 runners use their preinstalled MSYS2 `bsdtar` only to extract the
downloaded bootstrap archive; native builds then use that downloaded MSYS2 runtime.

Configure the `dockerhub` GitHub environment with variable `DOCKERHUB_USERNAME` and
secret `DOCKERHUB_TOKEN`. Configure repository Actions secret
`TASKCLUSTER_ACCESS_TOKEN` for client `project/fuzzing/worker-orion-gha-publish-gh`.
The worker client needs `queue:claim-work:proj-fuzzing/orion-gha-publish`,
`queue:worker-id:proj-fuzzing/gh-orion-publish-*`,
`queue:create-task:highest:proj-fuzzing/orion-gha-publish`,
`queue:create-task:project:none`, `queue:scheduler-id:taskcluster-github`, and
`queue:route:index.project.fuzzing.orion.*`. Task resolution and reclaim use the
claimed task's task credentials. The `.taskcluster.yml` decision role also needs
`queue:create-task:highest:proj-fuzzing/orion-gha-publish`,
`queue:create-task:project:none`, `queue:scheduler-id:taskcluster-github`, and
`queue:route:index.project.fuzzing.orion.*`.

The workflow's `GITHUB_TOKEN` has Actions artifact read access and contents read
access. The worker writes that token to a mode-0600 file for import tasks and strips
the raw credential from generic-worker's environment and logs. Import task IDs bind
the repository, revision, workflow run, attempt, and exact artifact. A failed-job-only
workflow rerun without a full set of attempt artifacts stops with instructions to
rerun all jobs.

Disable the old external Taskcluster Orion expiry cron hook when enabling this
workflow; otherwise both schedulers may rebuild expiring environments. The legacy
hook is external deployment configuration and is not changed by this repository.
