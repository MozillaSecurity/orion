## Local Development

The production Dockerfile uses Taskcluster secrets to fetch credentials for our private FuzzManager instance. If you do not have the credentials of your FuzzManager instance stored in a KMS or similar database and/or you want to develop on this image then the following examples are recommended.

Building locally:

    TAG=dev
    docker build -t mozillasecurity/libfuzzer:$TAG ../.. -f Dockerfile

... or to test the latest build:

    TAG=latest

Testing locally:

    eval $(TASKCLUSTER_ROOT_URL=https://community-tc.services.mozilla.com taskcluster signin)
    LOGS="logs-$(date +%Y%m%d%H%M%S)"
    mkdir -p "$LOGS"
    docker run --rm -it \
        -e TASKCLUSTER_ROOT_URL \
        -e TASKCLUSTER_CLIENT_ID \
        -e TASKCLUSTER_ACCESS_TOKEN \
        -v "$(pwd)/$LOGS":/logs \
        mozillasecurity/libfuzzer:$TAG 2>&1 | tee "$LOGS/live.log"

... add any environment variables required by the fuzzer using `-e VAR=value`

### Example: LibFuzzer Coverage Run

```bash
REVISION="$(curl --compressed -sSL https://community-tc.services.mozilla.com/api/index/v1/task/project.fuzzing.coverage-revision.latest/artifacts/public/coverage-revision.txt)"
fuzzfetch --build "$REVISION" --asan --fuzzing --coverage --gtest -n firefox

docker run \
    -h `uname -n` \
    -v ~/.fuzzmanagerconf:/home/worker/.fuzzmanagerconf \
    -v $PWD/firefox/:/home/worker/firefox \
    -e NO_SECRETS=1 \
    -e COVERAGE=1 \
    -e COVRUNTIME=600 \
    -e LIBFUZZER_ARGS=-max_total_time=180 \
    -e TOKENS=dicts/sdp.dict \
    -e FUZZER=SdpParser \
    -e CORPORA=samples/sdp/ \
    --rm -it mozillasecurity/libfuzzer
```

It is recommended to reserve at least 4GB of memory for containers running coverage runs to prevent OOMs of `grcov`.

### Example: LibFuzzer Run

```bash
fuzzfetch --fuzzing --asan --gtest -n firefox

docker run \
    -h `uname -n` \
    -v ~/.fuzzmanagerconf:/home/worker/.fuzzmanagerconf \
    -v $PWD/firefox/:/home/worker/firefox \
    -e NO_SECRETS=1 \
    -e TOKENS=dicts/sdp.dict \
    -e FUZZER=SdpParser \
    -e CORPORA=samples/sdp/ \
    --rm -it mozillasecurity/libfuzzer
```

Alternatively use a command from above and attach `bash -li` to overwrite the default set `CMD` which spawns `setup.sh` and to enter a shell instead. The environment variables are kept and you can run the `setup.sh` script manually.

You can obain the paths for `TOKENS` and `CORPORA` from the https://github.com/mozillasecurity/fuzzdata repository and these will automatically get fetched into the container.

If you want to use local corpora you can mount the folder containing the corpora into the container.

```bash
docker run \
    -h `uname -n` \
    -v ~/.fuzzmanagerconf:/home/worker/.fuzzmanagerconf \
    -v LOCAL_FOLDER:/home/worker/corpora/ \
    -e NO_SECRETS=1 \
    -e FUZZER=Dav1dDecode \
    --rm -it mozillasecurity/libfuzzer
```

In case you run the container on EC2 or a similar service, you can use `-e SHIP=<ProviderName>` and omit the `-h` parameter, which will determine the correct hostname of the container host for sending it to FuzzManager.
