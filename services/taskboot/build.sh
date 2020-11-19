#!/bin/sh -xe

create_cert () {
  # create a self-signed server cert
  # in /root/srv.pem & key in /root/srvkey.pem
  # & install the CA cert
  # expires in 1 day
  openssl req -x509 -newkey rsa:4096 -sha256 -keyout /root/cakey.pem -out /root/ca.pem -days 1 -nodes -subj '/CN=localhost'
  openssl req -newkey rsa:4096 -sha256 -keyout /root/srvkey.pem -out /root/srvreq.csr -nodes -subj '/CN=localhost'
  openssl x509 -req -in /root/srvreq.csr -sha256 -CA /root/ca.pem -CAkey /root/cakey.pem -CAcreateserial -out /root/srv.pem -days 1
  cp /root/ca.pem /usr/share/ca-certificates/localhost.crt
  echo "localhost.crt" >> /etc/ca-certificates.conf
  update-ca-certificates
}

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
  if [ "$BUILD_TOOL" == "img" ]; then
    create_cert
    # start a Docker registry at localhost
    REGISTRY_LOG_ACCESSLOG_DISABLED=true REGISTRY_LOG_LEVEL=warn \
      REGISTRY_HTTP_ADDR=0.0.0.0:443 REGISTRY_HTTP_TLS_CERTIFICATE=/root/srv.pem REGISTRY_HTTP_TLS_KEY=/root/srvkey.pem \
      registry serve /root/registry.yml&
  fi
  # retrieve image archives from dependency tasks to /images
  mkdir /images
  taskboot retrieve-artifact --output-path /images --artifacts public/**.tar
  # load images into the img image store via Docker registry
  find /images -name *.tar | while read img; do
    if [ "$BUILD_TOOL" == "img" ]; then
      dep="$(basename "$img" .tar)"
      skopeo copy "docker-archive:$img" "docker://localhost/mozillasecurity/$dep:latest"
      img pull "localhost/mozillasecurity/$dep:latest"
      img tag "localhost/mozillasecurity/$dep:latest" "docker.io/mozillasecurity/$dep:latest"
      img tag "localhost/mozillasecurity/$dep:latest" "docker.io/mozillasecurity/$dep:$GIT_REVISION"
    else
      docker import "$img"
    fi
    rm "$img"
  done
fi

# use taskboot to build the image
taskboot build --build-tool "$BUILD_TOOL" --image "mozillasecurity/$IMAGE_NAME" --tag "$GIT_REVISION" --tag latest --write "$ARCHIVE_PATH" "$DOCKERFILE"
