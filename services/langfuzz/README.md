Building locally:

    TAG=dev
    docker build -t mozillasecurity/langfuzz:$TAG ../.. -f Dockerfile

... or to test the latest build:

    TAG=latest

Testing locally:

    eval $(TASKCLUSTER_ROOT_URL=https://community-tc.services.mozilla.com taskcluster signin)
    LOGS="logs-$(date +%Y%m%d%H%M%S)"
    mkdir -p "$LOGS"
    docker run --rm -e TASKCLUSTER_ROOT_URL -e TASKCLUSTER_CLIENT_ID -e TASKCLUSTER_ACCESS_TOKEN --privileged -it -v "$(pwd)/$LOGS":/logs mozillasecurity/langfuzz:$TAG 2>&1 | tee "$LOGS/live.log"

... add any environment variables required by the fuzzer using `-e VAR=value`
