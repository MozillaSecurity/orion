#### Example: Domino
```bash
eval $(TASKCLUSTER_ROOT_URL=https://community-tc.services.mozilla.com taskcluster signin)
docker run \
-e DOMINO_ROOT=domino \
-e ADAPTER=dominode \
-e TARGET=asan \
-e IGNORE="log-limit memory timeout" \
-e COLLECT=5 \
-e INSTANCES_PER_CORE=0 \
-e TOOLNAME=grizzly-domino \
-e TIMEOUT=90 \
-e INPUT=domino/package.json \
-e PREFS=default \
-e RELAUNCH=250 \
-e MEM_LIMIT=7000 \
-e TASKCLUSTER_ROOT_URL \
-e TASKCLUSTER_CLIENT_ID \
-e TASKCLUSTER_ACCESS_TOKEN \
--rm -it mozillasecurity/grizzly
docker exec -uworker -it $CID /bin/bash
```
