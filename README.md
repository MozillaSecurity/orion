![Logo](https://github.com/posidron/posidron.github.io/raw/master/static/images/fuzzos.png)


### Contents
* OS: Ubuntu zesty
* Pre-installed: AFL, Honggfuzz, FuzzManager, FuzzFetch


[![Current Release](assets/overview.png)](assets/overview.png)

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
docker login --username=XYZ
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
