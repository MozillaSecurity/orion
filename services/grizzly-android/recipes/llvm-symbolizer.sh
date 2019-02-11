#!/bin/bash -ex

# install build requirements
apt-get update -y -qq
apt-get install -q -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        curl \
        libpython2.7-stdlib \
        ninja-build \
        p7zip-full \
        python2.7-minimal \
        subversion

# download and extract android-ndk
curl -L https://dl.google.com/android/repository/android-ndk-r17b-linux-x86_64.zip -o /tmp/android-ndk.zip
7z x /tmp/android-ndk.zip
mv android-ndk-*/ android-ndk
rm /tmp/android-ndk.zip

# checkout llvm
svn co -q "https://llvm.org/svn/llvm-project/llvm/tags/RELEASE_701/final@349247" llvm

# configure and build
rm -rf build
mkdir build
cd build
export CFLAGS
CFLAGS="-D__ANDROID_API__=21 -isystem $PWD/../android-ndk/sysroot/usr/include -isystem $PWD/../android-ndk/sysroot/usr/include/x86_64-linux-android -fdata-sections -ffunction-sections -O3"
cmake \
    -GNinja \
    -DCMAKE_ANDROID_ARCH_ABI=x86_64 \
    -DCMAKE_ANDROID_NDK="$PWD/../android-ndk" \
    -DCMAKE_ANDROID_NDK_TOOLCHAIN_VERSION=clang \
    -DCMAKE_ANDROID_STL_TYPE=c++_static \
    -DCMAKE_ASM_FLAGS="$CFLAGS -pie" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_FLAGS="$CFLAGS -pie" \
    -DCMAKE_CXX_FLAGS="$CFLAGS -pie -Qunused-arguments" \
    -DCMAKE_EXE_LINKER_FLAGS="-Wl,--gc-sections -pie" \
    -DCMAKE_SYSROOT="$PWD/../android-ndk/platforms/android-21/arch-x86_64" \
    -DCMAKE_SYSTEM_NAME=Android \
    -DCMAKE_SYSTEM_VERSION=21 \
    -DLLVM_ENABLE_ASSERTIONS=OFF \
    -DLLVM_TARGETS_TO_BUILD=X86 \
    -DLLVM_TOOL_LIBCXX_BUILD=ON \
    -DPYTHON_EXECUTABLE=/usr/bin/python2.7 \
    ../llvm
ninja llvm-symbolizer
strip bin/llvm-symbolizer
