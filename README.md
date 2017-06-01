# FuzzOS

### Build
```
docker build --squash -t posidron/fuzzos:latest -t posidron/fuzzos:v1 .
```

### Run
```
docker run -it --rm posidron/fuzzos:latest bash -li
```

### Push
```
docker login --username=posidron
docker push posidron/fuzzing-os:latest
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
