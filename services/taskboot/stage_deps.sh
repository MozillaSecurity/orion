#!/bin/sh -xe

retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="${i+1}"; done; "$@"; }

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
  dep="$(basename "$img" .tar)"
  if [ "$BUILD_TOOL" == "img" ]; then
    retry skopeo copy "docker-archive:$img" "docker://localhost/mozillasecurity/$dep:latest"
    retry img pull "localhost/mozillasecurity/$dep:latest"
    img tag "localhost/mozillasecurity/$dep:latest" "docker.io/mozillasecurity/$dep:latest"
    img tag "localhost/mozillasecurity/$dep:latest" "docker.io/mozillasecurity/$dep:$GIT_REVISION"
  else
    docker import "$img" "docker.io/mozillasecurity/$dep:latest"
    docker tag "docker.io/mozillasecurity/$dep:latest" "docker.io/mozillasecurity/$dep:$GIT_REVISION"
  fi
  rm "$img"
done
