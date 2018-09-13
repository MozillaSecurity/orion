#!/bin/bash -ex

#### Execute FuzzManager in runserver mode

cd $HOME/FuzzManager/server
python3 manage.py runserver
