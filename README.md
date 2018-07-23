<p align="center">
  <img src="https://github.com/posidron/posidron.github.io/raw/master/static/images/orion.png" alt="Logo" />
</p>

<p align="center">
  Monorepo for building and publishing multiple 🐳  containers as microservices within a single repository.
</p>
<p align="center">
<a href="https://travis-ci.org/MozillaSecurity/orion"><img src="https://travis-ci.org/MozillaSecurity/orion.svg?branch=master"></a>
<br/><br/>
FuzzOS<br>
  <a href="https://microbadger.com/images/mozillasecurity/fuzzos"><img src="https://images.microbadger.com/badges/image/mozillasecurity/fuzzos.svg"></a>
</p>

> For spawning a cluster of Docker containers at EC2 or other cloud providers, see the parent project [Laniakea](https://github.com/MozillaSecurity/laniakea/).

## Table of Contents

- [Table of Contents](#table-of-contents)
- [FuzzOS](#fuzzos)
- [Pre-Installed Packages](#pre-installed-packages)
- [Run](#run)
- [Documentation](#documentation)
- [Architecture](#architecture)
- [Build Instructions](#build-instructions)
  - [Usage](#usage)
  - [Testing](#testing)
  - [Login](#login)


This repository is a monorepo of various microservices and home of FuzzOS. CI and CD are performed with Travis and the Monorepo Manager script. Each image is either tagged with the latest revision, nightly or latest. For further information take either a look into the Wiki or the corresponding README.md of each microservice.



## FuzzOS

Base: Ubuntu Artful

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

## Documentation

- https://github.com/mozillasecurity/fuzzos/wiki

## Architecture

[![](docs/assets/overview.png)](https://raw.githubusercontent.com/MozillaSecurity/fuzzos/master/docs/assets/overview.png)

## Build Instructions

### Usage

```
make help
```

### Testing

```bash
make lint
```

### Login

```bash
DOCKER_USER=ABC make login
```
