#!/bin/bash -ex

cd $HOME

git clone --depth 1 https://github.com/mozillasecurity/fuzzmanager.git
cd fuzzmanager
pip install -r requirements.txt
python2 setup.py install
cd -

cat > $HOME/.fuzzmanagerconf << EOL
[Main]
serverhost = fuzzmanager.fuzzing.mozilla.org
serverport = 443
serverproto = https
serverauthtoken = 10bbb62108fcb0411ed0387420e3d7097c8d8045
sigdir = /home/worker/signatures
EOL
echo "clientid =" `hostname` >> $HOME/.fuzzmanagerconf
