== Orion Decision ==

This project includes code for handling Github Webhook events,
scheduling Orion build/test tasks, scheduling CI build matrix,
and running CI tasks.

It is also used by pre-commit hooks to validate the Orion service
definitions and CI build matrix definitions.

### GitHub Actions publication workers

The publication workflow uses the Taskcluster provisioner `proj-fuzzing` and
dedicated worker type `orion-gha-publish`. Configure the Taskcluster worker
client `project/fuzzing/worker-orion-gha-publish-gh` for that worker type, and
store its access token as the repository Actions secret
`TASKCLUSTER_ACCESS_TOKEN`. The client needs the generic-worker claim, resolve,
reclaim, and worker-id scopes for `proj-fuzzing/orion-gha-publish`, plus task
creation and route scopes for `index.project.fuzzing.orion.*` used by the
artifact import tasks. The `taskcluster-github` decision role needs permission
to create `proj-fuzzing/orion-gha-publish` tasks and route those publication
tasks to the Orion index namespace.

The workflow also needs Actions artifact read access, supplied by its scoped
`GITHUB_TOKEN`. That token is written to a mode-0600 file for generic-worker
tasks; raw GitHub tokens are removed from the worker environment. Docker image
publication uses the existing `DOCKERHUB_USERNAME` variable and
`DOCKERHUB_TOKEN` secret. Keep the `ORION_DOCKER_PUBLISH` repository variable
enabled only when the Docker `:latest` manifest push is authorized; selected
native-only publication runs do not need Docker credentials.

The import task IDs bind a repository, revision, workflow run, attempt, and
artifact key. A failed-job-only workflow rerun may not have a complete set of
attempt-specific build artifacts; in that case manifest creation fails with a
rerun-all instruction instead of importing artifacts from another attempt.
