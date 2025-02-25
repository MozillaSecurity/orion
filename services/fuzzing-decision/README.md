# Fuzzing automated deployment on Taskcluster

This Python 3 project manages Taskcluster resources and their deployment using public [community configuration](https://github.com/taskcluster/community-tc-config/) & private fuzzing configuration.

It uses [tc-admin](https://github.com/taskcluster/tc-admin) to allow admins to easily update those resources using a Git workflow.

A docker image is produced and stored [as Taskcluster artifacts](https://community-tc.services.mozilla.com/tasks/index/project.fuzzing.config). The [stable image](https://community-tc.services.mozilla.com/tasks/index/project.fuzzing.config/master) used in production, is built from the master branch of this repository.

## Running in production

Three modes of execution are available through the same code base (and Docker image):

1. Using `tc-admin` on a CI/CD git workflow of private configuration repositories, to manage resources.
2. Using `fuzzing-decision` in a Taskcluster hook or task, to bootstrap a fuzzing workflow across several tasks in the same group.
3. Using `fuzzing-pool-launch` as a Docker image entrypoint, which detects if it is running in a Taskcluster deployment, and if so uses the private fuzzing configuration repository to load a private command-line and environment, as well as redirect stdout/err to a private log artifact.

### Managing resources

The goal of this project is to create Taskcluster hooks that will run fuzzers continuously, across several tasks.

So we need to manage:
- Worker pools, either on AWS or GCP,
- [Hooks](https://community-tc.services.mozilla.com/hooks/), to describe fuzzers usage,
- Roles, to allow execution of said hooks.

tc-admin has several modes (`diff`, `apply` to update resources, `generate` to view the current configuration).
It should be used as a Taskcluster CI pipeline on a private configuration repository:
- running `tc-admin diff` on a pull request to view the potential changes.
- running `tc-admin apply` on a merge to the master branch. No credentials are needed, as all Taskcluster actions will go through the taskcluster proxy.

This pipeline is configured using the Taskcluster secret described below.

Produced hooks are triggered automatically at a specified cadence, but can also be triggered manually by administrators.

Each hook will create a decision task using this code, and will run the `fuzzing-decision` Python executable.

### Fuzzing workflow

A fuzzing workflow starts by an execution of the decision task.

That task will:
1. retrieve configuration from a Taskcluster secret, set with `TASKCLUSTER_SECRET` environment variable,
2. setup the ssh private key
3. clone the community repository, and the configured private fuzzing repository,
4. load the fuzzing pool configuration specified by the CLI args,
5. create dependent tasks in the same task group, following the fuzzing configuration for that pool.

Children tasks simply run a fuzzer, using the configured docker image & Taskcluster scopes.

### Taskcluster Secret

A Taskcluster secret is used by both modes to be able to clone private repositories:

```yaml
---

# Repository with public base information for the Taskcluster instance
community_config:
  url: 'https://github.com/taskcluster/community-tc-config.git'
  revision: master

# Repository with private fuzzing configuration
fuzzing_config:
  url: 'git@github.com:project/repo.git'
  revision: master

# This private key is used to clone private repositories
private_key: |
  -----BEGIN OPENSSH PRIVATE KEY-----
  XXXX
  -----END OPENSSH PRIVATE KEY-----
```

## Developer setup

To contribute or simply run locally this project, you need to do the following:

```bash
# Create a virtualenv
mkvirtualenv -p /usr/bin/python3 fuzzing-decision

# Install dependencies and project in editable mode
pip install -e .

# Now you can run tc-admin (with a local configuration)
tc-admin diff --fuzzing-configuration=path/to/config.yml
```

To run unit tests:

```bash
pip install tox
tox
```

To run linting:

```bash
pre-commit install

# will run on new commits now
pre-commit run -a
```

You can also build locally the docker image, using a simple `docker build`:

```bash
docker build -t fuzzing-decision .
```

### Local configuration

It's possible to replace Taskcluster secret usage by a local YAML configuration file that uses the same syntax. It allows an administrator to test changes on private repositories before publishing them, as you can specify a local git repository instead of a remote:

```yaml
---

# Use a local community configuration
community_config:
  path: /path/to/taskcluster/community-tc-config

# Use a local fuzzing configuration
fuzzing_config:
  path: /path/to/mozilla/private-fuzzing-config
  url: git@github.com:mozilla/private-fuzzing-config.git
  revision: refs/heads/master
```

To use that file, specify the following arguments:
- `--fuzzing-configuration=path/to/conf.yml` **for tc-admin**
- `--configuration=path/to/conf.yml` for **fuzzing-decision**

### Applying changes

As a fuzzing admin, you are able to publish changes without relying on the CI/CD pipeline, but you need to [create a Taskcluster client](https://community-tc.services.mozilla.com/auth/clients/create) with the following scopes:

```
assume:hook-id:project-fuzzing/*
auth:create-role:hook-id:project-fuzzing/*
auth:update-role:hook-id:project-fuzzing/*
hooks:modify-hook:project-fuzzing/*
queue:create-task:highest:proj-fuzzing/*
queue:scheduler-id:fuzzing
queue:cancel-task:fuzzing/*
secrets:get:project/fuzzing/decision
worker-manager:manage-worker-pool:proj-fuzzing/*
worker-manager:provider:community-tc-workers-*
```

This set of scopes allows you to:

- manage fuzzing hooks
- trigger fuzzing hooks
- create fuzzing hooks that can create tasks themselves
- read the decision secret, and allow hooks to read it
- manage fuzzing worker pools

On the community taskcluster instance, you need to prefix your client name with your own ClientId ([found on your profile](https://community-tc.services.mozilla.com/profile))

Once your client is created, you'll get a client id and access token.

You can then run `tc-admin apply` with those credentials:

```bash
export TASKCLUSTER_CLIENT_ID="<your_client_id>"
export TASKCLUSTER_ACCESS_TOKEN="<your_acess_token>"

tc-admin apply --fuzzing-configuration=path/to/config.yml --grep Role
tc-admin apply --fuzzing-configuration=path/to/config.yml --grep WorkerPool
tc-admin apply --fuzzing-configuration=path/to/config.yml
```
