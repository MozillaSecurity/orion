# FuzzOS

### Contents
* OS: Ubuntu zesty
* Pre-installed: AFL, FuzzManager, FuzzFetch


* https://hub.docker.com/u/posidron/
* https://hub.docker.com/u/taskclusterprivate/

### Build
```
docker build --squash -t posidron/fuzzos:latest -t posidron/fuzzos:v1 .
```

### Run
```
docker run -it --rm posidron/fuzzos:latest bash -li
```

### Run with custom environment
```
docker run -e ENV_NAME=value -it --rm posidron/fuzzos:latest bash -li
```

### Push
```
docker login --username=posidron
docker push posidron/fuzzos:latest
```

### Overview
```
docker images
docker ps
```

### Destroy
```
docker rmi -f $(docker images -a -q) &&  docker rm -f $(docker ps -a -q)
```


### References
* https://tools.taskcluster.net/task-creator/
* https://docs.docker.com/engine/reference/builder/
* https://dxr.mozilla.org/mozilla-central/source/taskcluster/docker/
* https://github.com/wsargent/docker-cheat-sheet
