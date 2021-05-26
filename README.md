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
    - [Known Issues](#known-issues)
    - [error creating overlay mount to /var/lib/docker/overlay2/<...>/merged: device or resource busy](#error-creating-overlay-mount-to-varlibdockeroverlay2merged-device-or-resource-busy)
  - [Architecture](#architecture)

### What is Orion?

Orion is a build environment for containerized services we run in our Fuzzing infrastructure (eg. [libFuzzer](https://github.com/MozillaSecurity/orion/tree/master/services/libfuzzer)).

> For spawning a cluster of Docker containers at EC2 or other cloud providers, see the parent project [Laniakea](https://github.com/MozillaSecurity/laniakea/).

### How does it operate?

CI and CD are performed autonomously with Taskcluster and the [Orion Decision](https://github.com/MozillaSecurity/orion/tree/master/services/orion-decision) service. A build process gets initiated only if a file of a particular service has been modified, or if a parent image is modified. Each image is either tagged with the latest `revision` or `latest` before being published to the [Docker registry](https://hub.docker.com/u/mozillasecurity/) and as [Taskcluster artifacts](https://community-tc.services.mozilla.com/tasks/index/project.fuzzing.orion). For more information about each service take a look in the corresponding README.md of each service or check out the [Wiki](https://github.com/MozillaSecurity/orion/wiki) pages for FAQs and a Docker cheat sheet.

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

Before a build task is initiated in Taskcluster, each shell script and Dockerfile undergo a linting and testing process which may or may not abort each succeeding task. To ensure your Dockerfile passes, you are encouraged to install the [`pre-commit`](https://pre-commit.com/) hook (`pre-commit install`) prior to commit, and to run any tests defined in the service folder before pushing your commit.
