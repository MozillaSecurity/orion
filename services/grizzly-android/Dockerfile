# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM mozillasecurity/grizzly:latest

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

USER root

COPY \
    services/grizzly-android/emulator_install.py \
    services/grizzly-android/pyproject.toml \
    services/grizzly-android/setup.cfg \
    services/grizzly-android/setup.py \
    services/grizzly-android/setup.sh \
    /src/emulator_install/
RUN /src/emulator_install/setup.sh
COPY services/grizzly-android/kvm.sh /home/worker/

COPY services/grizzly-android/android-x86_64-llvm-symbolizer \
    /home/worker/android-ndk/prebuilt/android-x86_64/llvm-symbolizer/llvm-symbolizer
RUN chown -R worker:worker /home/worker/android-ndk

CMD ["/bin/sh", "-c", "/home/worker/kvm.sh && /home/worker/launch-grizzly.sh"]
