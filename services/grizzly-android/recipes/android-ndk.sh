#!/bin/bash -ex

# install build requirements
apt-get update -qq
apt-get install -q -y --no-install-recommends \
        ca-certificates \
        curl \
        p7zip-full

# download and extract android-ndk
curl -L https://dl.google.com/android/repository/android-ndk-r17b-linux-x86_64.zip -o /tmp/android-ndk.zip
7z x /tmp/android-ndk.zip
mv android-ndk-*/ android-ndk
rm /tmp/android-ndk.zip

# download symbolizer from build server
curl -LO https://build.fuzzing.mozilla.org/builds/android-x86_64-llvm-symbolizer
