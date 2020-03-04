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

# download and extract clang
RUN curl --retry 5 -L https://index.taskcluster.net/v1/task/gecko.cache.level-3.toolchains.v3.linux64-clang-8-android-cross.latest/artifacts/public/build/clang.tar.xz -o /tmp/clang.tar.xz \
    && tar xJf /tmp/clang.tar.xz clang/lib64/clang/8.0.0/lib/linux/ \
    && rm /tmp/clang.tar.xz

# download symbolizer from build server
RUN curl --retry 5 -LO https://build.fuzzing.mozilla.org/builds/android-x86_64-llvm-symbolizer

FROM mozillasecurity/grizzly:latest

USER root

ARG BUILD_CLANG_VERSION=8.0.0
ENV CLANG_VERSION ${BUILD_CLANG_VERSION}
ENV CLANG_SRC clang/lib64/clang/${CLANG_VERSION}
ENV CLANG_DEST android-ndk/toolchains/llvm/prebuilt/linux-x86_64/lib64/clang/${CLANG_VERSION}

COPY services/grizzly-android/recipes/ /tmp/recipes/
RUN /tmp/recipes/setup.sh \
    && rm -rf /tmp/recipes
COPY services/grizzly-android/recipes/kvm.sh /home/worker/

COPY --from=symbolizer-build \
    /out/android-x86_64-llvm-symbolizer \
    /home/worker/android-ndk/prebuilt/android-x86_64/llvm-symbolizer/llvm-symbolizer
COPY --from=symbolizer-build \
    /out/${CLANG_SRC}/lib/linux/libclang_rt.asan-x86_64-android.so \
    /home/worker/${CLANG_DEST}/lib/linux/libclang_rt.asan-x86_64-android.so
COPY --from=symbolizer-build \
    /out/${CLANG_SRC}/lib/linux/libclang_rt.asan-i686-android.so \
    /home/worker/${CLANG_DEST}/lib/linux/libclang_rt.asan-i686-android.so
RUN chown -R worker:worker /home/worker/android-ndk

CMD ["/bin/sh", "-c", "/home/worker/kvm.sh && /home/worker/launch-grizzly.sh"]
