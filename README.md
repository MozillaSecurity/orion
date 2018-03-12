<p align="center">
  <img src="https://github.com/posidron/posidron.github.io/raw/master/static/images/fuzzos.png" alt="Logo" />
</p>

<p align="center">
Base builder image for Docker fuzzing containers for running at Mozilla TaskCluster and Amazon EC2.
</p>

<p align="center">
  <a href="https://travis-ci.org/MozillaSecurity/fuzzos"><img src="https://api.travis-ci.org/MozillaSecurity/fuzzos.svg?branch=master" alt="Build Status"></a>
  <a href="https://hub.docker.com"><img src="https://img.shields.io/docker/automated/taskclusterprivate/fuzzos.svg" alt="Docker Automation Status"></a>
  <a href="https://hub.docker.com"><img src="https://img.shields.io/docker/build/taskclusterprivate/fuzzos.svg" alt="Docker Build Status"></a>
  <a href="https://www.irccloud.com/invite?channel=%23fuzzing&amp;hostname=irc.mozilla.org&amp;port=6697&amp;ssl=1"><img src="https://img.shields.io/badge/IRC-%23fuzzing-1e72ff.svg?style=flat" alt="IRC"></a>
</p>


> For spawning a cluster of Docker containers at EC2, see the parent project <a href="https://github.com/MozillaSecurity/laniakea/">Laniakea</a>.


<h2>Table of Contents</h2>

* [OS](#OS)
* [Packages](#Packages)
* [Architecture](#Architecture)
* [Instructions](#BuildInstructions)
  * [Usage](#Usage)
  * [Login](#Login)
* [TaskCluster: TaskCreator Example](#TaskClusterTaskCreator)


<a name="OS"><h2>OS</h2></a>

OS: Ubuntu Artful

<a name="Packages"><h2>Pre-Installed Packages</h2></a>

* credstash
* fuzzfetch
* fuzzmanager
* afl
* honggfuzz
* llvm
* minidump
* rr

<a name="Architecture"><h2>Architecture</h2></a>

<p align="center">
  <a href="assets/overview.png"><img src="assets/overview.png"></a>
</p>


<a name="BuildInstructions"><h2>Build Instructions</h2></a>

> The Makefile is intended for developing purposes only. FuzzOS is built automatically after each push to this repository.

<a name="Usage"><h3>Usage</h3></a>

```bash
make help
```

<a name="Login"><h3>Login</h3></a>

```bash
DOCKER_USER=ABC make login
```



<a name="TaskClusterTaskCreator"><h2>TaskCluster: TaskCreator Example</h2></a>

This is an example task configuration which shows how Framboise would run at TaskCluster.

```json
provisionerId: aws-provisioner-v1
workerType: fuzzer
schedulerId: gecko-level-1
priority: lowest
retries: 5
created: '2017-06-06T22:05:12.240Z'
deadline: '2017-06-07T22:05:12.240Z'
expires: '2018-06-07T22:05:12.240Z'
scopes:
  - 'docker-worker:image:taskclusterprivate/framboise:*'
payload:
  image: 'taskclusterprivate/framboise:v1'
  command:
    - ./framboise.py
    - '-settings'
    - settings/framboise.linux.docker.yaml
    - '-fuzzer'
    - '1:Canvas2D'
    - '-debug'
    - '-restart'
  maxRunTime: 600
  env:
    FUZZER_MAX_RUNTIME: 570
routes:
  - notify.email.cdiehl@mozilla.com.on-failed
  - notify.irc-user.posidron.on-any
metadata:
  name: 'Fuzzer: framboise'
  description: 'Fuzzer: framboise'
  owner: cdiehl@mozilla.com
  source: 'https://tools.taskcluster.net/task-creator/'
```
