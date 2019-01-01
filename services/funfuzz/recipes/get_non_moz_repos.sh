#!/bin/bash -ex

# shellcheck disable=SC1090
source ~/.common.sh

pushd "$HOME"

GITFLAGS="retry git clone -v --depth 1 --no-tags "

$GITFLAGS https://github.com/MozillaSecurity/autobisect autobisect
$GITFLAGS https://github.com/WebAssembly/binaryen binaryen
$GITFLAGS https://github.com/MozillaSecurity/ffpuppet ffpuppet
$GITFLAGS https://github.com/MozillaSecurity/octo octo
$GITFLAGS https://github.com/MozillaSecurity/funfuzz funfuzz
# Clone awsm only if the access key is found
if [[ -f "$HOME/.ssh/id_rsa.fuzz" ]]
then
  $GITFLAGS git@framagit.org:bnjbvr/awsm.git awsm
fi

popd
