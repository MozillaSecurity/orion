# FuzzOS

### Contents
* OS: Ubuntu zesty
* Pre-installed: AFL, FuzzManager, FuzzFetch


* https://hub.docker.com/u/posidron/
* https://hub.docker.com/u/taskclusterprivate/
* https://mozillians.org/en-US/group/sec-fuzzing/
* https://tools.taskcluster.net/auth/roles/#mozillians-group:sec-fuzzing
* https://hub.docker.com/r/taskclusterprivate/framboise
* https://tools.taskcluster.net/task-creator/

### Build
```bash
docker build --squash -t posidron/fuzzos:latest -t posidron/fuzzos:v1 .
```

### Run
```bash
docker run -it --rm posidron/fuzzos:latest bash -li
```

### Run with custom environment
```bash
docker run -e ENV_NAME=value -it --rm posidron/fuzzos:latest bash -li
```

### Push
```bash
docker login --username=posidron
docker push posidron/fuzzos:latest
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



## Example setup for Framboise

### .dockerignore
```
*.md
public
tests
.git
Dockerfile
.DS_Store
.dockerignore
```

### Xvfb wrapper
```bash
#!/bin/bash -ex
cd $HOME

python fuzzfetch/fetch.py -o $HOME -n firefox -a

cd framboise
xvfb-run -s '-screen 0 1024x768x24' $@ &
sleep ${FUZZER_MAX_RUNTIME:-600}; kill $(ps -s $$ -o pid=)
```

### Dockerfile
```bash
FROM posidron/fuzzos:latest

LABEL maintainer Christoph Diehl <cdiehl@mozilla.com>

COPY . framboise

USER root
RUN \
  apt-get update -q \
  && apt-get install -y -q --no-install-recommends --no-install-suggests \
    firefox \
  && apt-get clean -y \
  && apt-get autoclean -y \
  && apt-get autoremove -y \
  && rm -rf /var/lib/apt/lists/ \
  && rm -rf /root/.cache/* \
  && cd framboise && python3 setup.py \
  && chown -R worker:worker /home/worker

USER worker
ENTRYPOINT ["framboise/xvfb.sh"]
#CMD ["/bin/bash", "--login"]
```


### Build and push fuzzing image to private Hub
```bash
docker build --squash -t posidron/framboise:latest -t taskclusterprivate/framboise:v1 .
docker push taskclusterprivate/framboise:v1
```


### TaskCluster: TaskCreator
```json
{
  "provisionerId": "aws-provisioner-v1",
  "workerType": "dbg-linux64",
  "priority": "lowest",
  "retries": 5,
  "created": "2017-06-03T02:02:53.247Z",
  "deadline": "2017-06-04T02:02:53.247Z",
  "expires": "2018-06-04T02:02:53.247Z",
  "scopes": [
    "docker-worker:image:taskclusterprivate/framboise:*"
  ],
  "payload": {
    "image": "taskclusterprivate/framboise:v1",
    "command": [
      "./framboise.py", "-settings", "settings/framboise.linux.docker.yaml",
      "-fuzzer", "1:Canvas2D",
      "-debug", "-restart"
    ],
    "maxRunTime": 600,
    "env": {
      "FUZZER_MAX_RUNTIME": 570,
    }
  },
  "metadata": {
    "name": "Fuzzer: framboise",
    "description": "Fuzzer: framboise",
    "owner": "cdiehl@mozilla.com",
    "source": "https://tools.taskcluster.net/task-creator/"
  },
}
```


### References
* https://docs.taskcluster.net/
* https://docs.docker.com/engine/reference/builder/
* https://dxr.mozilla.org/mozilla-central/source/taskcluster/docker/
* https://github.com/wsargent/docker-cheat-sheet
