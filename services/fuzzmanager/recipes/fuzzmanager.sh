#!/bin/bash -ex

#### Install FuzzManager and its server mode requirements

cd /home/fuzzmanager
git clone --depth 1 --no-tags https://github.com/mozillasecurity/FuzzManager.git
python3 -m pip install /home/fuzzmanager/FuzzManager

cd /home/fuzzmanager/FuzzManager
python3 -m pip install --upgrade -r server/requirements.txt

### Set up FuzzManager

cd /home/fuzzmanager/FuzzManager/server/
python3 manage.py migrate
# python3 manage.py createsuperuser
# # input fuzzmanager as username
# # input password
# python3 manage.py get_auth_token FuzzManager
# # Note the auth_token

# Temporarily go to the home directory of the fuzzmanager user for htpasswd
pushd /home/fuzzmanager
# htpasswd -cb .htpasswd fuzzmanager <token>
popd

# Create a FuzzManager configuration file
cat << EOF > /home/fuzzmanager/.fuzzmanagerconf
[Main]
serverhost = 127.0.0.1
serverport = 8000
serverproto = http
serverauthtoken = <token>
sigdir = /home/fuzzmanager/sigdir/
tool = your-favourite-tool
EOF
