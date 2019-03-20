FROM ubuntu:18.04 AS symbolizer-build

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

COPY recipes/ /tmp/recipes
WORKDIR /root
RUN /tmp/recipes/android-ndk.sh

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
    /root/android-x86_64-llvm-symbolizer \
    /home/worker/android-ndk/prebuilt/android-x86_64/llvm-symbolizer/llvm-symbolizer
COPY --from=symbolizer-build \
    /root/${CLANG_PATH}/lib/linux/libclang_rt.asan-x86_64-android.so \
    /home/worker/${CLANG_PATH}/lib/linux/libclang_rt.asan-x86_64-android.so
COPY --from=symbolizer-build \
    /root/${CLANG_PATH}/lib/linux/libclang_rt.asan-i686-android.so \
    /home/worker/${CLANG_PATH}/lib/linux/libclang_rt.asan-i686-android.so
RUN chown -R worker:worker /home/worker/android-ndk

CMD ["/bin/sh", "-c", "/home/worker/kvm.sh && su worker -c /home/worker/launch-grizzly.sh"]
