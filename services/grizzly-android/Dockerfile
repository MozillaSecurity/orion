FROM ubuntu:18.04 AS symbolizer-build

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

COPY recipes/ /tmp/recipes
WORKDIR /root
RUN /tmp/recipes/android-ndk.sh

FROM mozillasecurity/grizzly:latest

USER root
COPY recipes/ /tmp/recipes/
RUN /tmp/recipes/all.sh \
    && rm -rf /tmp/recipes
COPY recipes/kvm.sh /home/worker/

COPY --from=symbolizer-build \
    /root/build/bin/llvm-symbolizer \
    /home/worker/android-ndk/prebuilt/android-x86_64/llvm-symbolizer/llvm-symbolizer
COPY --from=symbolizer-build \
    /root/android-ndk/toolchains/llvm/prebuilt/linux-x86_64/lib64/clang/6.0.2/lib/linux/libclang_rt.asan-x86_64-android.so \
    /home/worker/android-ndk/toolchains/llvm/prebuilt/linux-x86_64/lib64/clang/6.0.2/lib/linux/libclang_rt.asan-x86_64-android.so
COPY --from=symbolizer-build \
    /root/android-ndk/toolchains/llvm/prebuilt/linux-x86_64/lib64/clang/6.0.2/lib/linux/libclang_rt.asan-i686-android.so \
    /home/worker/android-ndk/toolchains/llvm/prebuilt/linux-x86_64/lib64/clang/6.0.2/lib/linux/libclang_rt.asan-i686-android.so
RUN chown -R worker:worker /home/worker/android-ndk

CMD ["/bin/sh", "-c", "/home/worker/kvm.sh && su worker -c /home/worker/launch-grizzly.sh"]
