<p align="center"><img src="docs/assets/orion.png" alt="Orion logo" title="Orion"></p>

<p align="center">
<a href="https://community-tc.services.mozilla.com/api/github/v1/repository/MozillaSecurity/orion/master/latest"><img src="https://community-tc.services.mozilla.com/api/github/v1/repository/MozillaSecurity/orion/master/badge.svg" alt="Task Status"></a>
<a href="https://riot.im/app/#/room/#fuzzing:mozilla.org"> <img src="https://img.shields.io/badge/dynamic/json?color=green&label=chat&query=%24.chunk[%3F(%40.canonical_alias%3D%3D%22%23fuzzing%3Amozilla.org%22)].num_joined_members&suffix=%20users&url=https%3A%2F%2Fmozilla.modular.im%2F_matrix%2Fclient%2Fr0%2FpublicRooms&style=flat&logo=matrix" alt="Matrix"></a>
</p>

Monorepo for building and publishing multiple Docker containers as microservices within a single repository.

## Table of Contents

- [Table of Contents](#table-of-contents)
  - [What is Orion?](#what-is-orion)
  - [How does it operate?](#how-does-it-operate)
  - [Build Instructions and Development](#build-instructions-and-development)
    - [Usage](#usage)
    - [Testing](#testing)

### What is Orion?

Orion is a build environment for containerized services we run in our Fuzzing infrastructure (eg. [libFuzzer](https://github.com/MozillaSecurity/orion/tree/master/services/libfuzzer)).

> For spawning a cluster of Docker containers at EC2 or other cloud providers, see the parent project [Laniakea](https://github.com/MozillaSecurity/laniakea/).

### How does it operate?

GitHub Actions runs the generated Orion service dependency graph for pull requests, pushes to `master`, a weekly expiry check, and manual rebuilds. The graph selects only affected tests and builds. Successful `master` runs publish Docker `:latest` manifests and import service archives into Taskcluster, preserving the existing artifact and index routes used by downstream workers. See [Orion Decision](services/orion-decision/README.md) for repository and Taskcluster configuration. For service details, see each service README or the [Wiki](https://github.com/MozillaSecurity/orion/wiki).

### Build Instructions and Development

#### Usage

You can build, test and push locally, which is great for testing locally. The commands below are general,
and each service may have more specific instructions defined in the README.md of the service.

    TAG=dev
    docker build -t mozillasecurity/service:$TAG ../.. -f Dockerfile

... or to test the latest build:

    TAG=latest

Running the fuzzer locally:

    eval $(TASKCLUSTER_ROOT_URL=https://community-tc.services.mozilla.com taskcluster signin)
    LOGS="logs-$(date +%Y%m%d%H%M%S)"
    mkdir -p "$LOGS"
    docker run --rm -e TASKCLUSTER_ROOT_URL -e TASKCLUSTER_CLIENT_ID -e TASKCLUSTER_ACCESS_TOKEN -it -v "$(pwd)/$LOGS":/logs mozillasecurity/service:$TAG 2>&1 | tee "$LOGS/live.log"

... add any environment variables required by the fuzzer using `-e VAR=value`. Some fuzzer images alter kernel sysctls and will require `docker run --privileged`.

#### Testing

GitHub Actions runs the selected service tests and builds for each pull request and `master` push. To catch formatting and service definition issues locally, install the [`pre-commit`](https://pre-commit.com/) hooks with `pre-commit install` and run any tests defined in the service folder before pushing your commit.
