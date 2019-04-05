# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM alpine:latest AS symbolizer-build

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

WORKDIR /out

# install build requirements
RUN apk add --no-cache \
        curl \
        p7zip

# download and extract android-ndk
RUN curl --retry 5 -L https://dl.google.com/android/repository/android-ndk-r17b-linux-x86_64.zip -o /tmp/android-ndk.zip \
    && 7z x /tmp/android-ndk.zip \
    && mv android-ndk-*/ android-ndk \
    && rm /tmp/android-ndk.zip

# download symbolizer from build server
RUN curl --retry 5 -LO https://build.fuzzing.mozilla.org/builds/android-x86_64-llvm-symbolizer

FROM mozillasecurity/grizzly:latest

USER root

ARG BUILD_CLANG_VERSION=6.0.2
ENV CLANG_VERSION ${BUILD_CLANG_VERSION}
ENV CLANG_PATH android-ndk/toolchains/llvm/prebuilt/linux-x86_64/lib64/clang/${CLANG_VERSION}

COPY recipes/ /tmp/recipes/
RUN /tmp/recipes/all.sh \
    && rm -rf /tmp/recipes
COPY recipes/kvm.sh /home/worker/

COPY --from=symbolizer-build \
    /out/android-x86_64-llvm-symbolizer \
    /home/worker/android-ndk/prebuilt/android-x86_64/llvm-symbolizer/llvm-symbolizer
COPY --from=symbolizer-build \
    /out/${CLANG_PATH}/lib/linux/libclang_rt.asan-x86_64-android.so \
    /home/worker/${CLANG_PATH}/lib/linux/libclang_rt.asan-x86_64-android.so
COPY --from=symbolizer-build \
    /out/${CLANG_PATH}/lib/linux/libclang_rt.asan-i686-android.so \
    /home/worker/${CLANG_PATH}/lib/linux/libclang_rt.asan-i686-android.so
RUN chown -R worker:worker /home/worker/android-ndk

CMD ["/bin/sh", "-c", "/home/worker/kvm.sh && su worker -c /home/worker/launch-grizzly.sh"]
