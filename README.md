![Orion](docs/assets/orion.png "Orion logo")

<h2 align="center">Orion</h2>

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

You can build, test and push locally, which is great for testing locally. In order to do
that run the command below and adjust the path to the service you want to interact and the
repository `DOCKER_ORG` to which you intent to push. `DOCKER_ORG` is used as tag name for the image.

> Note that you might want to edit the `service.yaml` of the image too, if you intent to make use of
> custom `build_args`, parent images and manifest destinations.

```bash
#!/usr/bin/env bash
export DOCKER_ORG=<DOCKER_USERNAME>
export TRAVIS_PULL_REQUEST=false
export TRAVIS_BRANCH=master
export TRAVIS_EVENT_TYPE=cron
./monorepo.py -ci travis -build -test -deliver -path core/linux
./monorepo.py -ci travis -build -test -deliver -path base/linux/fuzzos
```

```
make help
```

#### Testing

Before a build task is initiated in Taskcluster, each shell script and Dockerfile undergo a linting and testing process which may or may not abort each succeeding task. To ensure your Dockerfile passes, you are encouraged to install the [`pre-commit`](https://pre-commit.com/) hook (`pre-commit install`) prior to commit, and to run any tests defined in the service folder before pushing your commit.

#### Known Issues

#### error creating overlay mount to /var/lib/docker/overlay2/<...>/merged: device or resource busy

Workaround: https://github.com/docker/for-linux/issues/711

```
$ sudo systemctl stop docker
$ sudo nano /etc/docker/daemon.json
{
  "max-concurrent-uploads": 1
}
$ sudo systemctl start docker
$ docker push [...]
```
