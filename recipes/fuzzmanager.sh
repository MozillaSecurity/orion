#!/bin/bash -ex

pip install git+https://github.com/mozillasecurity/fuzzmanager.git

cat > $HOME/.fuzzmanagerconf << EOF
[Main]
serverhost = fuzzmanager.fuzzing.mozilla.org
serverport = 443
serverproto = https
serverauthtoken = 10bbb62108fcb0411ed0387420e3d7097c8d8045
sigdir = $HOME/signatures
EOF
echo "clientid = $(hostname)" >> $HOME/.fuzzmanagerconf

mkdir $HOME/signatures
