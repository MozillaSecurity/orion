#!/bin/bash -ex

cd /root
set +x
curl -sSL http://taskcluster/secrets/v1/secret/project/fuzzing/deploy-domino-web-tests | jshon -e secret -e key -u >.ssh/id_ecdsa.domino_web_tests
curl -sSL http://taskcluster/secrets/v1/secret/project/fuzzing/deploy-domino | jshon -e secret -e key -u >.ssh/id_rsa.domino
curl -sSL http://taskcluster/secrets/v1/secret/project/fuzzing/deploy-gridl | jshon -e secret -e key -u >.ssh/id_rsa.gridl
curl -sSL http://taskcluster/secrets/v1/secret/project/fuzzing/deploy-octo-private | jshon -e secret -e key -u >.ssh/id_rsa.octo
set -x
chmod 0400 .ssh/id_ecdsa.domino_web_tests .ssh/id_rsa.domino .ssh/id_rsa.gridl .ssh/id_rsa.octo

git clone git@domino-web-tests:MozillaSecurity/domino-web-tests
cd domino-web-tests
npm install
npm update domino gridl
git commit -a -m "Update package-lock.json"
git push
