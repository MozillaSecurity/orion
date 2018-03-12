#!/bin/sh -e
for i in $(seq 1 5); do $@ && break || sleep 1; done
