# Orion GitHub Actions CI

`ci.graph` validates service and recipe metadata. `ci.plan` compares the
workflow revision with the last successful main-branch publication and emits
the dirty services, tests, recipes, and build dependencies. The checked-in
`.github/workflows/orion.yml` is generated from that dependency graph:

```sh
uv sync --project ci --locked --no-dev
uv run --project ci --locked --no-dev python -m ci.graph --check
uv run --project ci --locked --no-dev python -m ci.workflows --check
uv run --project ci --locked --no-dev python -m ci.workflows --write
```

Run these commands from the repository root. `ci/uv.lock` pins the toolchain;
after changing dependencies in `ci/pyproject.toml`, refresh it with
`uv lock --project ci --upgrade`. Run the CI tooling tests with
`uv run --project ci --locked python -m pytest -q ci/tests`.

Pull requests run the Python tox matrix, root lint, and Linux recipe checks,
then build changed service images and MSYS bundles. Publishing is limited to
trusted runs on `main`; pull requests never receive publishing credentials.
The weekly schedule rebuilds and publishes all services. A manual run can
rebuild everything with the `rebuild_all` input.

The Docker Hub secrets are `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`. Taskcluster
publication needs `TASKCLUSTER_CLIENT_ID` and `TASKCLUSTER_ACCESS_TOKEN`; the
default Taskcluster root is `https://firefox-ci-tc.services.mozilla.com` and
can be overridden with the `TASKCLUSTER_ROOT_URL` repository variable. The
Taskcluster client needs these scopes, with matching task scopes for public
artifacts:

```text
queue:create-task:highest:proj-fuzzing/gh-pub-*
queue:claim-work:proj-fuzzing/gh-pub-*
queue:worker-id:github-actions/*
queue:create-artifact:public/*
assume:worker-id:github-actions/pub-*
queue:scheduler-id:github-actions
index:insert-task:project.fuzzing.orion.*
```

Configure the `github-actions` scheduler, `proj-fuzzing` provisioner access,
and matching client role in Firefox CI Taskcluster before enabling trusted
publishing. Configure the `main` branch protection to require the
`Orion CI and builds / complete` check before merging.

The reusable build workflow saves Docker archives and MSYS bundles as Actions
artifacts. The trusted publisher consumes those archives and creates the
Taskcluster artifacts and registry tags. The scheduled run refreshes published
artifacts before they expire.
