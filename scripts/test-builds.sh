#!/usr/bin/env bash

export DOCKER_ORG=posidron

TRAVIS_PULL_REQUEST=false TRAVIS_BRANCH=master TRAVIS_EVENT_TYPE=cron ./monorepo.py -ci travis -build -test -deliver -path core/linux
TRAVIS_PULL_REQUEST=false TRAVIS_BRANCH=master TRAVIS_EVENT_TYPE=cron ./monorepo.py -ci travis -build -test -deliver -path base/linux/fuzzos
TRAVIS_PULL_REQUEST=false TRAVIS_BRANCH=master TRAVIS_EVENT_TYPE=cron ./monorepo.py -ci travis -build -test -deliver -path services/credstash

TRAVIS_PULL_REQUEST=false TRAVIS_BRANCH=master TRAVIS_EVENT_TYPE=cron ./monorepo.py -ci travis -build -test -deliver -path services/funfuzz
TRAVIS_PULL_REQUEST=false TRAVIS_BRANCH=master TRAVIS_EVENT_TYPE=cron ./monorepo.py -ci travis -build -test -deliver -path services/grizzly
TRAVIS_PULL_REQUEST=false TRAVIS_BRANCH=master TRAVIS_EVENT_TYPE=cron ./monorepo.py -ci travis -build -test -deliver -path services/grizzly-android
TRAVIS_PULL_REQUEST=false TRAVIS_BRANCH=master TRAVIS_EVENT_TYPE=cron ./monorepo.py -ci travis -build -test -deliver -path services/fuzzmanager
TRAVIS_PULL_REQUEST=false TRAVIS_BRANCH=master TRAVIS_EVENT_TYPE=cron ./monorepo.py -ci travis -build -test -deliver -path services/libfuzzer
TRAVIS_PULL_REQUEST=false TRAVIS_BRANCH=master TRAVIS_EVENT_TYPE=cron ./monorepo.py -ci travis -build -test -deliver -path services/u2f-hid-rs
