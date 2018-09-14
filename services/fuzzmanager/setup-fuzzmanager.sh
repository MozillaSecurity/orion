#!/bin/bash -ex

#### Install FuzzManager and its server mode requirements

HOME="/home/fuzzmanager"
cd $HOME
if [[ ! -d "$HOME/FuzzManager" ]] ; then
    git clone --depth 1 --no-tags https://github.com/MozillaSecurity/FuzzManager.git
    python3 -m pip install --user --upgrade $HOME/FuzzManager
fi

cd $HOME/FuzzManager
python3 -m pip install --user --upgrade -r server/requirements.txt

### Set up FuzzManager

cd $HOME/FuzzManager/server/
python3 manage.py migrate
python3 manage.py shell <<- EOF
from django.contrib.auth.models import User
User.objects.create_superuser(username="fuzzmanager", password="temppwd", email="foo@bar.com")
exit()
EOF
AUTHTOKEN="$(python3 manage.py get_auth_token fuzzmanager)"

# Temporarily go to the home directory of the fuzzmanager user for htpasswd
pushd $HOME
htpasswd -cb .htpasswd fuzzmanager "${AUTHTOKEN}"
popd

# Create a FuzzManager configuration file
cat << EOF > $HOME/.fuzzmanagerconf
[Main]
serverhost = 127.0.0.1
serverport = 8000
serverproto = http
serverauthtoken = ${AUTHTOKEN}
sigdir = /home/fuzzmanager/sigdir/
tool = your-favourite-tool
EOF
