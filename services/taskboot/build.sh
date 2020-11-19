#!/bin/sh -xe

if {
  [ $# -ne 0 ] ||
  [ -z "$ARCHIVE_PATH" ] ||
  [ -z "$DOCKERFILE" ] ||
  [ -z "$GIT_REPOSITORY" ] ||
  [ -z "$GIT_REVISION" ] ||
  [ -z "$IMAGE_NAME" ] ||
  {
    [ "$BUILD_TOOL" != "img" ] && [ "$BUILD_TOOL" != "dind" ]
  } ||
  {
    [ "$LOAD_DEPS" != "1" ] && [ "$LOAD_DEPS" != "0" ]
  }
}; then
  set +x
  echo "usage: $0"
  echo
  echo "Required environment variables:"
  echo
  echo "  ARCHIVE_PATH: Path to the image tar (output)."
  echo "  BUILD_TOOL: Tool to use for building (img/dind)."
  echo "  DOCKERFILE: Path to the Dockerfile."
  echo "  GIT_REPOSITORY: Repository holding the build context."
  echo "  GIT_REVISION: Commit to clone the repository at."
  echo "  IMAGE_NAME: Docker image name (eg. for mozillasecurity/taskboot, IMAGE_NAME=taskboot)."
  echo "  LOAD_DEPS: Must be 0/1. If 1, pull all images built in dependency tasks into the image store."
  echo
  echo "The container also requires \`--privileged\` to run \`img\`."
  echo
  exit 2
fi >&2

if [ "$LOAD_DEPS" == "1" ]; then
  stage_deps
fi

# use taskboot to build the image
taskboot build --build-tool "$BUILD_TOOL" --image "mozillasecurity/$IMAGE_NAME" --tag "$GIT_REVISION" --tag latest --write "$ARCHIVE_PATH" "$DOCKERFILE"
