#!/usr/bin/env bash

set -e
set -x

#### Install NodeJS

curl -sL https://deb.nodesource.com/setup_10.x | bash -
apt-get install -y nodejs
