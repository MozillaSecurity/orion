retry () { i=0; while [ $i -lt 9 ]; do "$@" && return || sleep 30; i="$((i+1))"; done; "$@"; }

create_cert () {
  # create a self-signed server cert
  # in /root/srv.pem & key in /root/srvkey.pem
  # & install the CA cert
  # expires in 1 day
  openssl req -x509 -newkey rsa:4096 -sha256 -keyout /root/cakey.pem -out /root/ca.pem -days 1 -nodes -subj '/CN=localhost'
  openssl req -newkey rsa:4096 -sha256 -keyout /root/srvkey.pem -out /root/srvreq.csr -nodes -subj '/CN=localhost'
  openssl x509 -req -in /root/srvreq.csr -sha256 -CA /root/ca.pem -CAkey /root/cakey.pem -CAcreateserial -out /root/srv.pem -days 1
  cp /root/ca.pem /usr/share/ca-certificates/localhost.crt
  mkdir -p /root/.docker
  cp /root/ca.pem /root/.docker/ca.pem
  echo "localhost.crt" >> /etc/ca-certificates.conf
  update-ca-certificates
}

start_registry () {
  REGISTRY_LOG_ACCESSLOG_DISABLED=true REGISTRY_LOG_LEVEL=warn \
    REGISTRY_HTTP_ADDR=0.0.0.0:443 REGISTRY_HTTP_TLS_CERTIFICATE=/root/srv.pem REGISTRY_HTTP_TLS_KEY=/root/srvkey.pem \
    registry serve /root/registry.yml&
}
