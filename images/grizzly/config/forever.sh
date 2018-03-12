#!/bin/sh -e
while true; do "$@" || sleep 60; done
