## Local Development

The production Dockerfile uses credstash to fetch FuzzManager credentials.
If you do not have your credentials stored in a KMS or similar database and want to provide the credentials
locally by yourself and/or you want to develop on the image, then the following approach is recommended.


### Coverage Run

```bash
REVISION=$(curl -sL https://build.fuzzing.mozilla.org/builds/coverage-revision.txt)

fuzzfetch --build "$REVISION" --fuzzing --coverage -a --tests gtest -n firefox
hg clone -r "$REVISION" https://hg.mozilla.org/mozilla-central

docker run \
    -v ~/.fuzzmanagerconf:/home/worker/.fuzzmanagerconf \
    -v ~/mozilla-central/:/home/worker/mozilla-central \
    -v ~/firefox/:/home/worker/firefox \
    -e COVERAGE=1 -e COVRUNTIME=130 -e LIBFUZZER_ARGS=-max_total_time=100 -e TOKENS=dicts/sdp.dict -e FUZZER=SdpParser -e CORPORA=samples/sdp/ \
    --rm -it mozillasecurity/libfuzzer
```
