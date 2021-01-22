#### Example: Faulty
```bash
CID=$(docker run \
-e MOZ_IPC_MESSAGE_LOG=1 \
-e FAULTY_PROBABILITY=40000 \
-e FAULTY_LARGE_VALUES=1 \
-e FAULTY_ENABLE_LOGGING=1 \
-e FAULTY_PICKLE=1 \
-e FAULTY_PARENT=1 \
-e CORPMAN=ipc \
-e TARGET="-a --fuzzing" \
-e CACHE=4 \
-e INSTANCES=3 \
-e TOOLNAME=grizzly-ipc-faulty \
-e FAULTY_PARENT=1 \
-e TIMEOUT=45 \
-e INPUT=grammars/html-fuzz.gmr \
-e PREFS=prefs/prefs-default-e10s.js \
-e RELAUNCH=100 \
-dit mozillasecurity/grizzly:latest /bin/bash)
docker exec -it $CID /bin/bash
```

#### Example: Domino
```bash
CID=$(docker run \
-e DOMINO_ROOT=domino \
-e CORPMAN=dominode \
-e TARGET=asan \
-e IGNORE="log-limit memory timeout" \
-e BEARSPRAY=1 \
-e CACHE=5 \
-e INSTANCES_PER_CORE=0 \
-e TOOLNAME=grizzly-domino \
-e TIMEOUT=90 \
-e INPUT=domino/package.json \
-e PREFS=prefs/prefs-default-e10s.js \
-e RELAUNCH=250 \
-e MEM_LIMIT=7000 \
-v $HOME/.aws:/home/worker/.aws \
-dit mozillasecurity/grizzly:latest)
docker exec -uworker -it $CID /bin/bash
```

#### Run
```bash
docker run -dit -e ENV taskclusterprivate/grizzly:latest /bin/bash
```

#### Enter the container (1)
```bash
docker exec -it <CONTAINER_ID> /bin/bash
```

#### Enter the container (2)
###### **Note**: Needs ^P^Q to exit without destroying the container.
```bash
docker attach <CONTAINER_ID>
```

#### Stop
```bash
docker stop <CONTAINER_ID>
```

#### References

* https://blog.docker.com/2014/06/why-you-dont-need-to-run-sshd-in-docker/
* https://stackoverflow.com/questions/28212380/why-docker-container-exits-immediately
