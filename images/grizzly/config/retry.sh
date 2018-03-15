#!/bin/sh -e

# shellcheck disable=SC2015
for _ in $(seq 1 5); do "$@" && break || sleep 1; done
