#!/bin/sh -xe

create-cert () {
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

if [ $# -ne 4 ]; then
  echo "$0 build_name build_path fetch_rev output_image" >&2
  exit 2
fi
build_name="$1"
build_path="$2"
fetch_rev="$3"
output_image="$4"

if [ "$DEPS" == "true" ]; then
  create-cert
  REGISTRY_LOG_ACCESSLOG_DISABLED=true REGISTRY_LOG_LEVEL=warn \
    REGISTRY_HTTP_ADDR=0.0.0.0:443 REGISTRY_HTTP_TLS_CERTIFICATE=/root/srv.pem REGISTRY_HTTP_TLS_KEY=/root/srvkey.pem \
    registry serve /root/registry.yml&
  mkdir /images
  taskboot retrieve-artifact --output-path /images --artifacts public/**.tar
  find /images -name *.tar | while read img; do
    dep="$(basename "$img" .tar)"
    skopeo copy "docker-archive:$img" "docker://localhost/mozillasecurity/$dep:latest"
    img pull "localhost/mozillasecurity/$dep:latest"
    img tag "localhost/mozillasecurity/$dep:latest" "docker.io/mozillasecurity/$dep:latest"
    img tag "localhost/mozillasecurity/$dep:latest" "docker.io/mozillasecurity/$dep:$fetch_rev"
  done
fi
taskboot build --image "mozillasecurity/$build_name" --tag "$fetch_rev" --tag latest --write $output_image "$build_path/Dockerfile"
