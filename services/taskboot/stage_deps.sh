#!/bin/sh -xe

. /usr/local/share/taskboot_common.sh

if {
  [ $# -ne 0 ] ||
  [ -z "$GIT_REVISION" ] ||
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
  echo
  echo "The container also requires \`--privileged\` to run \`img\`."
  echo
  exit 2
fi >&2

create_cert
# retrieve image archives from dependency tasks to /images
mkdir /images
taskboot retrieve-artifact --output-path /images --artifacts public/**.tar
# load images into the img image store via Docker registry
if [ "$BUILD_TOOL" == "img" ]; then
  start_registry
fi
find /images -name *.tar | while read img; do
  dep="$(basename "$img" .tar)"
  if [ "$BUILD_TOOL" == "img" ]; then
    retry skopeo copy "docker-archive:$img" "docker://localhost/mozillasecurity/$dep:latest"
    retry img pull "localhost/mozillasecurity/$dep:latest"
    img tag "localhost/mozillasecurity/$dep:latest" "docker.io/mozillasecurity/$dep:latest"
    img tag "localhost/mozillasecurity/$dep:latest" "docker.io/mozillasecurity/$dep:$GIT_REVISION"
  else
    docker load < "$img"
    docker tag "docker.io/mozillasecurity/$dep:latest" "docker.io/mozillasecurity/$dep:$GIT_REVISION"
    docker tag "docker.io/mozillasecurity/$dep:latest" "localhost/mozillasecurity/$dep:latest"
    docker tag "docker.io/mozillasecurity/$dep:latest" "localhost/mozillasecurity/$dep:$GIT_REVISION"
  fi
  rm "$img"
done
