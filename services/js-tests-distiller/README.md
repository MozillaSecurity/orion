Building locally:

    TAG=dev
    docker build -t mozillasecurity/js-tests-distiller:$TAG ../.. -f Dockerfile

... or to test the latest build:

    TAG=latest

Testing locally:

    eval $(TASKCLUSTER_ROOT_URL=https://community-tc.services.mozilla.com taskcluster signin)
    OUT="js-tests-$(date +%Y%m%d%H%M%S)"
    mkdir -p "$OUT"
    docker run --rm -e TASKCLUSTER_ROOT_URL -e TASKCLUSTER_CLIENT_ID -e TASKCLUSTER_ACCESS_TOKEN -it -v "$(pwd)/$OUT":/home/ubuntu/output mozillasecurity/js-tests-distiller:$TAG 2>&1 | tee "$OUT/live.log"
