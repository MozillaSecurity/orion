<p align="center">
  <img src="https://github.com/posidron/posidron.github.io/raw/master/static/images/fuzzos.png" alt="Logo" />
</p>

<p align="center">
  Base builder image for Docker fuzzing containers which can be run at Mozilla TaskCluster, Amazon EC2 or locally.
</p>

<p align="center">
  <a href="https://microbadger.com/images/mozillasecurity/fuzzos"><img src="https://images.microbadger.com/badges/version/mozillasecurity/fuzzos.svg"></a>
  <a href="https://microbadger.com/images/mozillasecurity/fuzzos"><img src="https://images.microbadger.com/badges/image/mozillasecurity/fuzzos.svg"></a>
  <a href="https://microbadger.com/images/mozillasecurity/fuzzos"><img src="https://img.shields.io/docker/pulls/mozillasecurity/fuzzos.svg"></a>
</p>

> For spawning a cluster of Docker containers at EC2 or other cloud providers, see the parent project [Laniakea](https://github.com/MozillaSecurity/laniakea/).

## Table of Contents

- [Table of Contents](#table-of-contents)
- [OS](#os)
- [Pre-Installed Packages](#pre-installed-packages)
- [Run](#run)
- [Architecture](#architecture)
- [Build Instructions](#build-instructions)
  - [Usage](#usage)
  - [Login](#login)
  - [Testing](#testing)
- [Documentation](#documentation)

## OS

OS: Ubuntu Artful

## Pre-Installed Packages

- credstash
- fuzzfetch
- fuzzmanager
- afl
- honggfuzz
- llvm
- minidump
- rr
- grcov
- ripgrep
- nodejs

## Run

```bash
docker search fuzzos
docker run -it --rm mozillasecurity/fuzzos:latest bash -li
```

## Architecture

[![](docs/assets/overview.png)](https://raw.githubusercontent.com/MozillaSecurity/fuzzos/master/docs/assets/overview.png)

## Build Instructions

> The Makefile is intended for developing purposes only. FuzzOS is built automatically after each push to this repository.

### Usage

```
make help
```

### Login

```bash
DOCKER_USER=ABC make login
```

### Testing

```bash
make -k lint
```

## Documentation

- https://github.com/mozillasecurity/fuzzos/wiki
