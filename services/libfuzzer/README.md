## Local Development

The production Dockerfile uses credstash to fetch credentials for our private FuzzManager instance. If you do not have the credentials of your FuzzManager instance stored in a KMS or similar database and/or you want to develop on this image then the following approach is recommended.

### Example: LibFuzzer Coverage Run

```bash
REVISION=$(curl -sL https://build.fuzzing.mozilla.org/builds/coverage-revision.txt)
fuzzfetch --build "$REVISION" --fuzzing --coverage -a --gtest -n firefox

docker run \
    -h `hostname` \
    -v ~/.fuzzmanagerconf:/home/worker/.fuzzmanagerconf \
    -v ~/firefox/:/home/worker/firefox \
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
fuzzfetch --fuzzing --coverage -a --gtest -n firefox

docker run \
    -h `hostname` \
    -v ~/.fuzzmanagerconf:/home/worker/.fuzzmanagerconf \
    -v ~/firefox/:/home/worker/firefox \
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
 -h `hostname` \
 -v ~/.fuzzmanagerconf:/home/worker/.fuzzmanagerconf \
 -v LOCAL_FOLDER:/home/worker/corpora/ \
 -e FUZZER=Dav1dDecode \
 --rm -it mozillasecurity/libfuzzer
```

In case you run the container on EC2 or a similar service, you can use `-e SHIP=<ProviderName>` and omit the `-h` parameter, which will determine the correct hostname of the container host for sending it to FuzzManager.
