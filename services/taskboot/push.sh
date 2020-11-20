#!/bin/sh -xe

. /usr/local/share/taskboot_common.sh

login () {
  set +x
  TASKCLUSTER_ROOT_URL="${TASKCLUSTER_PROXY_URL-$TASKCLUSTER_ROOT_URL}" retry taskcluster api secrets get "$TASKCLUSTER_SECRET" -o /tmp/secret.json
  chmod 0400 /tmp/secret.json
  pair="$(jq -r .secret.docker.username /tmp/secret.json):$(jq -r .secret.docker.password /tmp/secret.json)"
  registry="$(jq -r .secret.docker.registry /tmp/secret.json)"
  rm /tmp/secret.json
  echo "{\"auths\":{\"https://$registry/v1\":{\"auth\":\"$(echo -n "$pair" | base64)\"}}}" > /tmp/skopeo-auth.json
  echo -n "$registry" > /tmp/registry.txt
  chmod 0400 /tmp/skopeo-auth.json
  set -x
}

if {
  [ $# -ne 0 ] ||
  [ -z "$GIT_REVISION" ] ||
  [ -z "$IMAGE_NAME" ] ||
  [ -z "$TASKCLUSTER_SECRET" ] ||
  {
    [ "$BUILD_TOOL" != "img" ] && [ "$BUILD_TOOL" != "dind" ]
  }
}; then
  set +x
  echo "usage: $0"
  echo
  echo "Required environment variables:"
  echo
  echo "  BUILD_TOOL: Tool to use for building (img/dind)."
  echo "  GIT_REVISION: Commit to clone the repository at."
  echo "  IMAGE_NAME: Docker image name (eg. for mozillasecurity/taskboot, IMAGE_NAME=taskboot)."
  echo "  TASKCLUSTER_SECRET: Docker Hub credentials"
  echo
  exit 2
fi >&2

if [ "$BUILD_TOOL" = "img" ]; then
  taskboot push-artifact
else
  stage_deps
  # push to local registry
  # registry has to be restarted *without* TLS for ancient docker client
  start_registry
  docker push "localhost/mozillasecurity/$IMAGE_NAME:latest"
  docker push "localhost/mozillasecurity/$IMAGE_NAME:$GIT_REVISION"
  # copy from local registry to docker hub
  # registry has to be restarted *with* TLS for skopeo
  start_registry_tls
  login
  registry="$(cat /tmp/registry.txt)"
  retry skopeo copy --authfile=/tmp/skopeo-auth.json "docker://localhost/mozillasecurity/$IMAGE_NAME:latest" "docker://$registry/mozillasecurity/$IMAGE_NAME:latest"
  retry skopeo copy --authfile=/tmp/skopeo-auth.json "docker://localhost/mozillasecurity/$IMAGE_NAME:latest" "docker://$registry/mozillasecurity/$IMAGE_NAME:$GIT_REVISION"
fi
