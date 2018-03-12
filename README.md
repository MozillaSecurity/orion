<p align="center">
  <img src="https://github.com/posidron/posidron.github.io/raw/master/static/images/fuzzos.png" alt="Logo" />
</p>

<p align="center">
FuzzOS is the base builder image for Docker fuzzing containers running at Mozilla TaskCluster and Amazon EC2.
</p>

<p align="center">
<a href="https://travis-ci.org/MozillaSecurity/fuzzos"><img src="https://api.travis-ci.org/MozillaSecurity/fuzzos.svg?branch=master" alt="Build Status"></a>
<a href="https://www.irccloud.com/invite?channel=%23fuzzing&amp;hostname=irc.mozilla.org&amp;port=6697&amp;ssl=1"><img src="https://img.shields.io/badge/IRC-%23fuzzing-1e72ff.svg?style=flat" alt="IRC"></a>
</p>


> For spawning a cluster of Docker containers at EC2, see the parent project Laniakea.


<h2>Table of Contents</h2>
<hr>

* [OS](#Packages)
* [Packages](#Packages)
* [Architecture](#Architecture)
* [Instructions](#BuildInstructions)
  * [Login](#)
  * [Build](#)
  * [Run](#)
  * [Push](#)
  * [Overview](#)
  * [Destroy](#)
* [TaskCluster: TaskCreator Example](#TaskClusterTaskCreator)



<a name="OS"><h2>OS</h2></a>
<hr>

OS: Ubuntu Artful

<a name="Packages"><h2>Packages</h2></a>
<hr>

* credstash
* fuzzfetch
* fuzzmanager
* afl
* honggfuzz
* llvm
* minidump
* rr


<a name="Architecture"><h2>Architecture</h2></a>
<hr>

<p align="center">
  <a href="assets/overview.png"><img src="assets/overview.png"></a>
</p>


<a name="BuildInstructions"><h2>Build Instructions</h2></a>
<hr>


<a name="Login"><h3>Login</h3></a>


```bash
docker login --username=XYZ
```

### Build
```bash
docker build --squash -t taskclusterprivate/fuzzos:latest -t taskclusterprivate/fuzzos:v1 .
```

### Run
```bash
docker run -it --rm taskclusterprivate/fuzzos:latest bash -li
docker run -e ENV_NAME=value -it --rm taskclusterprivate/fuzzos:latest bash -li
```

### Push
```bash
docker push taskclusterprivate/fuzzos:latest
docker push taskclusterprivate/fuzzos:v1
```

### Overview
```bash
docker images
docker ps
```

### Destroy
```bash
docker rmi -f $(docker images -a -q) &&  docker rm -f $(docker ps -a -q)
```

### Debug
Overwrite the ENTRYPOINT command to use /bin/bash with a UID of 0 (root).
```bash
docker run -u 0 --entrypoint=/bin/bash -it --rm taskclusterprivate/fuzzos:latest
```



### TaskCluster: TaskCreator

This is an example task configuration which shows how Framboise runs at TaskCluster.

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


### References
* https://hub.docker.com/u/taskclusterprivate/
* https://mozillians.org/en-US/group/sec-fuzzing/
* https://tools.taskcluster.net/auth/roles/#mozillians-group:sec-fuzzing
* https://tools.taskcluster.net/task-creator/
* https://tools.taskcluster.net/aws-provisioner/#fuzzer/view
* https://docs.taskcluster.net/
* https://docs.docker.com/engine/reference/builder/
* https://dxr.mozilla.org/mozilla-central/source/taskcluster/docker/
* https://github.com/wsargent/docker-cheat-sheet
* https://dxr.mozilla.org/mozilla-central/source/taskcluster/docker
